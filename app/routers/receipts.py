import os
import uuid
import csv
from io import StringIO
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session, joinedload

from ..database import get_db, Base, engine
from ..models import Receipt, ReceiptFile
from ..schemas import ReceiptCreate, ReceiptRead
from ..auth import get_current_user
from ..ocr_processor import ReceiptOCR
from ..pdf_merger import merge_files_to_pdf

Base.metadata.create_all(bind=engine)

router = APIRouter(prefix="/receipts", tags=["receipts"])  

UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "..", "uploads"))
UPLOAD_DIR = os.path.abspath(UPLOAD_DIR)
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.get("/", response_model=List[ReceiptRead])
def list_receipts(db: Session = Depends(get_db), user=Depends(get_current_user)):
    rows = (
        db.query(Receipt)
        .options(joinedload(Receipt.files))
        .filter(Receipt.user_id == user.id)
        .order_by(Receipt.uploaded_at.desc())
        .all()
    )
    return rows


@router.get("/export/csv")
def export_csv(db: Session = Depends(get_db), user=Depends(get_current_user)):
    receipts = (
        db.query(Receipt)
        .filter(Receipt.user_id == user.id)
        .order_by(Receipt.service_date.desc())
        .all()
    )
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Write info note
    writer.writerow(['NOTE: Receipt links require being logged in to http://192.168.1.100 in your browser before clicking'])
    writer.writerow([])
    
    # Write header
    writer.writerow([
        'Service Date', 'Provider', 'Patient Name', 'Category', 'Amount',
        'Payment Method', 'Paid Date', 'Submitted Date', 'Reimbursed',
        'Reimbursement Amount', 'Reimbursement Date', 'Claim Number',
        'Tax Year', 'HSA Eligible', 'Notes', 'Receipt Link', 'Uploaded At'
    ])
    
    # Write data rows
    for r in receipts:
        receipt_link = f"http://192.168.1.100/receipts/{r.id}/file"
        writer.writerow([
            r.service_date,
            r.provider,
            r.patient_name or '',
            r.category or '',
            r.amount or '',
            r.payment_method or '',
            r.paid_date or '',
            r.submitted_date or '',
            'Yes' if r.reimbursed else 'No',
            r.reimbursement_amount or '',
            r.reimbursement_date or '',
            r.claim_number or '',
            r.tax_year or '',
            'Yes' if r.hsa_eligible else 'No',
            r.notes or '',
            receipt_link,
            r.uploaded_at
        ])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=receipts_export_{datetime.now().strftime('%Y%m%d')}.csv"}
    )


@router.get("/analytics")
def get_analytics(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Get aggregated analytics data for visualizations"""
    receipts = db.query(Receipt).filter(Receipt.user_id == user.id).all()
    
    # Group by year
    by_year = {}
    by_category = {}
    
    for r in receipts:
        year = r.tax_year or (r.service_date.year if r.service_date else datetime.now().year)
        
        if year not in by_year:
            by_year[year] = {
                'total_spent': 0,
                'reimbursed': 0,
                'pending_reimbursement': 0,
                'not_submitted': 0,
                'hsa_eligible': 0,
                'count': 0
            }
        
        amount = float(r.amount) if r.amount else 0
        by_year[year]['total_spent'] += amount
        by_year[year]['count'] += 1
        
        if r.reimbursed and r.reimbursement_amount:
            by_year[year]['reimbursed'] += float(r.reimbursement_amount)
        elif r.submitted_date and not r.reimbursed:
            by_year[year]['pending_reimbursement'] += amount
        else:
            # Not yet submitted for reimbursement
            by_year[year]['not_submitted'] += amount
        
        if r.hsa_eligible:
            by_year[year]['hsa_eligible'] += amount
        
        # Category breakdown
        category = r.category or 'Uncategorized'
        by_category[category] = by_category.get(category, 0) + amount
    
    return {
        'by_year': by_year,
        'by_category': by_category,
        'total_receipts': len(receipts)
    }


def generate_claim_number(db: Session, user_id: int) -> str:
    """Generate unique claim number in format CLAIM-YYYY-NNN"""
    current_year = datetime.now().year
    prefix = f"CLAIM-{current_year}-"
    
    # Get highest number for current year
    last_claim = (
        db.query(Receipt)
        .filter(Receipt.user_id == user_id)
        .filter(Receipt.claim_number.like(f"{prefix}%"))
        .order_by(Receipt.claim_number.desc())
        .first()
    )
    
    if last_claim and last_claim.claim_number:
        try:
            last_num = int(last_claim.claim_number.split('-')[-1])
            next_num = last_num + 1
        except:
            next_num = 1
    else:
        next_num = 1
    
    return f"{prefix}{next_num:03d}"


@router.post("/", response_model=ReceiptRead)
async def upload_receipt(
    file: List[UploadFile] = File(...),
    service_date: str = Form(...),
    provider: str = Form(...),
    patient_name: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    amount: Optional[float] = Form(None),
    payment_method: Optional[str] = Form(None),
    paid_date: Optional[str] = Form(None),
    submitted_date: Optional[str] = Form(None),
    reimbursed: bool = Form(False),
    reimbursement_amount: Optional[float] = Form(None),
    reimbursement_date: Optional[str] = Form(None),
    claim_number: Optional[str] = Form(None),
    tax_year: Optional[int] = Form(None),
    hsa_eligible: bool = Form(True),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    # Auto-generate claim number if not provided
    if not claim_number:
        claim_number = generate_claim_number(db, user.id)
    
    # Create one receipt record
    rec = Receipt(
        user_id=user.id,
        service_date=datetime.strptime(service_date, "%Y-%m-%d").date(),
        provider=provider,
        patient_name=patient_name,
        category=category,
        amount=amount,
        payment_method=payment_method,
        paid_date=datetime.strptime(paid_date, "%Y-%m-%d").date() if paid_date else None,
        submitted_date=datetime.strptime(submitted_date, "%Y-%m-%d").date() if submitted_date else None,
        reimbursed=reimbursed,
        reimbursement_amount=reimbursement_amount,
        reimbursement_date=datetime.strptime(reimbursement_date, "%Y-%m-%d").date() if reimbursement_date else None,
        claim_number=claim_number,
        tax_year=tax_year,
        hsa_eligible=hsa_eligible,
        notes=notes,
    )
    db.add(rec)
    db.flush()  # Get the receipt ID
    
    # Save files temporarily
    files_list = file if isinstance(file, list) else [file]
    temp_paths = []
    
    for single_file in files_list:
        # generate unique filename with original extension
        ext = os.path.splitext(single_file.filename)[1]
        unique_name = f"{uuid.uuid4().hex}{ext}"
        target_path = os.path.join(UPLOAD_DIR, unique_name)

        # save file
        try:
            with open(target_path, "wb") as out:
                while True:
                    chunk = await single_file.read(8192)
                    if not chunk:
                        break
                    out.write(chunk)
            temp_paths.append(target_path)
        except Exception:
            db.rollback()
            # Clean up any saved files
            for path in temp_paths:
                if os.path.exists(path):
                    os.remove(path)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to save file {single_file.filename}")

    # Merge files if multiple, otherwise use single file
    try:
        print(f"DEBUG: Processing {len(temp_paths)} file(s)")
        if len(temp_paths) > 1:
            print(f"DEBUG: Merging {len(temp_paths)} files into single PDF")
            # Merge into single PDF
            merged_name = f"{uuid.uuid4().hex}.pdf"
            merged_path = os.path.join(UPLOAD_DIR, merged_name)
            merge_files_to_pdf(temp_paths, merged_path)
            print(f"DEBUG: Merge successful: {merged_path}")
            
            # Delete temporary files
            for path in temp_paths:
                os.remove(path)
            
            # Create single ReceiptFile record for merged PDF
            receipt_file = ReceiptFile(
                receipt_id=rec.id,
                file_name=merged_name,
                original_name=f"merged_{len(temp_paths)}_files.pdf",
                content_type="application/pdf",
            )
            db.add(receipt_file)
        else:
            # Single file - just create record
            original_filename = files_list[0].filename
            receipt_file = ReceiptFile(
                receipt_id=rec.id,
                file_name=os.path.basename(temp_paths[0]),
                original_name=original_filename,
                content_type=files_list[0].content_type,
            )
            db.add(receipt_file)
    except Exception as e:
        db.rollback()
        # Clean up files
        for path in temp_paths:
            if os.path.exists(path):
                os.remove(path)
        if len(temp_paths) > 1 and os.path.exists(merged_path):
            os.remove(merged_path)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to merge files: {str(e)}")
    
    db.commit()
    db.refresh(rec)
    return RedirectResponse(url="/receipts", status_code=303)


@router.post("/scan")
async def scan_receipt(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Scan receipt using OCR and extract structured data"""
    # Save file temporarily
    ext = os.path.splitext(file.filename)[1]
    temp_filename = f"temp_{uuid.uuid4().hex}{ext}"
    temp_path = os.path.join(UPLOAD_DIR, temp_filename)
    
    try:
        # Save uploaded file
        with open(temp_path, "wb") as out:
            while True:
                chunk = await file.read(8192)
                if not chunk:
                    break
                out.write(chunk)
        
        # Process with OCR
        ocr = ReceiptOCR()
        extracted_data = ocr.process_receipt(temp_path)
        
        return JSONResponse(content=extracted_data)
    
    except Exception as e:
        return JSONResponse(
            content={'error': f'OCR processing failed: {str(e)}'},
            status_code=500
        )
    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.get("/files/{file_id}")
def download_file_by_id(file_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """View or download a file by its ID directly"""
    receipt_file = db.query(ReceiptFile).filter(ReceiptFile.id == file_id).first()
    if not receipt_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    
    # Verify user owns the receipt
    rec = db.query(Receipt).filter(Receipt.id == receipt_file.receipt_id, Receipt.user_id == user.id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    
    path = os.path.join(UPLOAD_DIR, receipt_file.file_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing")
    
    # Use inline disposition to view in browser instead of downloading
    headers = {"Content-Disposition": f'inline; filename="{receipt_file.original_name}"'}
    return FileResponse(path, media_type=receipt_file.content_type, headers=headers)


@router.get("/{receipt_id}/file")
def download_receipt(receipt_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Download first file of a receipt (for backward compatibility)"""
    rec = db.query(Receipt).filter(Receipt.id == receipt_id, Receipt.user_id == user.id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    
    if not rec.files:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No files found for this receipt")
    
    # Return first file
    first_file = rec.files[0]
    path = os.path.join(UPLOAD_DIR, first_file.file_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing")
    
    headers = {"Content-Disposition": f'inline; filename="{first_file.original_name}"'}
    return FileResponse(path, media_type=first_file.content_type, headers=headers)


@router.get("/{receipt_id}/files/{file_id}")
def download_receipt_file(
    receipt_id: int, 
    file_id: int, 
    db: Session = Depends(get_db), 
    user=Depends(get_current_user)
):
    """Download a specific file from a receipt"""
    rec = db.query(Receipt).filter(Receipt.id == receipt_id, Receipt.user_id == user.id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    
    receipt_file = db.query(ReceiptFile).filter(
        ReceiptFile.id == file_id,
        ReceiptFile.receipt_id == receipt_id
    ).first()
    
    if not receipt_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    
    path = os.path.join(UPLOAD_DIR, receipt_file.file_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File missing")
    
    headers = {"Content-Disposition": f'inline; filename="{receipt_file.original_name}"'}
    return FileResponse(path, media_type=receipt_file.content_type, headers=headers)


@router.put("/{receipt_id}", response_model=ReceiptRead)
def update_receipt(
    receipt_id: int,
    service_date: Optional[str] = Form(None),
    provider: Optional[str] = Form(None),
    patient_name: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    amount: Optional[float] = Form(None),
    payment_method: Optional[str] = Form(None),
    paid_date: Optional[str] = Form(None),
    submitted_date: Optional[str] = Form(None),
    reimbursed: bool = Form(False),
    reimbursement_amount: Optional[float] = Form(None),
    reimbursement_date: Optional[str] = Form(None),
    claim_number: Optional[str] = Form(None),
    tax_year: Optional[int] = Form(None),
    hsa_eligible: bool = Form(True),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Update existing receipt fields"""
    rec = db.query(Receipt).filter(Receipt.id == receipt_id, Receipt.user_id == user.id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    
    # Update fields if provided
    if service_date:
        rec.service_date = datetime.strptime(service_date, "%Y-%m-%d").date()
    if provider:
        rec.provider = provider
    
    # String fields: empty string clears the field
    rec.patient_name = patient_name if patient_name else None
    rec.category = category if category else None
    rec.payment_method = payment_method if payment_method else None
    rec.claim_number = claim_number if claim_number else None
    rec.notes = notes if notes else None
    
    # Numeric fields: empty or None clears the field
    rec.amount = amount if amount else None
    rec.tax_year = tax_year if tax_year else None
    rec.reimbursement_amount = reimbursement_amount if reimbursement_amount else None
    
    # Date fields: empty string clears the field
    if paid_date:
        rec.paid_date = datetime.strptime(paid_date, "%Y-%m-%d").date()
    else:
        rec.paid_date = None
    
    if submitted_date:
        rec.submitted_date = datetime.strptime(submitted_date, "%Y-%m-%d").date()
    else:
        rec.submitted_date = None
    
    if reimbursement_date:
        rec.reimbursement_date = datetime.strptime(reimbursement_date, "%Y-%m-%d").date()
    else:
        rec.reimbursement_date = None
    
    # Boolean fields
    rec.reimbursed = reimbursed
    rec.hsa_eligible = hsa_eligible
    
    db.commit()
    db.refresh(rec)
    return rec


@router.delete("/files/{file_id}")
def delete_file(
    file_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete a specific file from a receipt"""
    receipt_file = db.query(ReceiptFile).filter(ReceiptFile.id == file_id).first()
    if not receipt_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    
    # Verify user owns the receipt
    receipt = db.query(Receipt).filter(Receipt.id == receipt_file.receipt_id, Receipt.user_id == user.id).first()
    if not receipt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    
    # Check if this is the last file - don't allow deleting the last file
    if len(receipt.files) <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete the last file. Delete the receipt instead.")
    
    # Delete physical file
    file_path = os.path.join(UPLOAD_DIR, receipt_file.file_name)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            pass  # Log but don't fail
    
    # Delete database record
    db.delete(receipt_file)
    db.commit()
    
    return {"message": "File deleted successfully"}


@router.delete("/files/{file_id}")
def delete_file(
    file_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete a specific file from a receipt"""
    receipt_file = db.query(ReceiptFile).filter(ReceiptFile.id == file_id).first()
    if not receipt_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    
    # Verify user owns the receipt
    receipt = db.query(Receipt).filter(Receipt.id == receipt_file.receipt_id, Receipt.user_id == user.id).first()
    if not receipt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    
    # Check if this is the last file - don't allow deleting the last file
    if len(receipt.files) <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete the last file. Delete the receipt instead.")
    
    # Delete physical file
    file_path = os.path.join(UPLOAD_DIR, receipt_file.file_name)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            pass  # Log but don't fail
    
    # Delete database record
    db.delete(receipt_file)
    db.commit()
    
    return {"message": "File deleted successfully"}


@router.delete("/{receipt_id}")
def delete_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Delete a receipt and all its files"""
    rec = db.query(Receipt).filter(Receipt.id == receipt_id, Receipt.user_id == user.id).first()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    
    # Delete all physical files
    for receipt_file in rec.files:
        file_path = os.path.join(UPLOAD_DIR, receipt_file.file_name)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                # Log error but don't fail the delete
                pass
    
    # Delete database record (cascade will delete receipt_files)
    db.delete(rec)
    db.commit()
    
    return {"message": "Receipt deleted successfully"}


@router.post("/{receipt_id}/add-files")
async def add_files_to_receipt(
    receipt_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Add additional files to an existing receipt (auto-merges if multiple)"""
    # Get the receipt
    receipt = db.query(Receipt).filter(Receipt.id == receipt_id, Receipt.user_id == user.id).first()
    if not receipt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Receipt not found")
    
    # Save files temporarily
    temp_paths = []
    for file in files:
        ext = os.path.splitext(file.filename)[1]
        unique_name = f"{uuid.uuid4().hex}{ext}"
        target_path = os.path.join(UPLOAD_DIR, unique_name)

        try:
            with open(target_path, "wb") as out:
                while True:
                    chunk = await file.read(8192)
                    if not chunk:
                        break
                    out.write(chunk)
            temp_paths.append(target_path)
        except Exception:
            # Clean up any saved files
            for path in temp_paths:
                if os.path.exists(path):
                    os.remove(path)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to save file {file.filename}")
    
    # Merge files if multiple, otherwise use single file
    try:
        print(f"DEBUG: Adding {len(temp_paths)} file(s) to receipt {receipt_id}")
        if len(temp_paths) > 1:
            print(f"DEBUG: Merging {len(temp_paths)} files into single PDF")
            # Merge into single PDF
            merged_name = f"{uuid.uuid4().hex}.pdf"
            merged_path = os.path.join(UPLOAD_DIR, merged_name)
            merge_files_to_pdf(temp_paths, merged_path)
            print(f"DEBUG: Merge successful: {merged_path}")
            
            # Delete temporary files
            for path in temp_paths:
                os.remove(path)
            
            # Create single ReceiptFile record for merged PDF
            receipt_file = ReceiptFile(
                receipt_id=receipt.id,
                file_name=merged_name,
                original_name=f"merged_{len(temp_paths)}_files.pdf",
                content_type="application/pdf",
            )
            db.add(receipt_file)
            db.commit()
            return {"message": f"Merged {len(temp_paths)} files into 1 PDF", "count": 1}
        else:
            # Single file - just create record
            receipt_file = ReceiptFile(
                receipt_id=receipt.id,
                file_name=os.path.basename(temp_paths[0]),
                original_name=files[0].filename,
                content_type=files[0].content_type,
            )
            db.add(receipt_file)
            db.commit()
            return {"message": f"Added 1 file to receipt", "count": 1}
    except Exception as e:
        db.rollback()
        # Clean up files
        for path in temp_paths:
            if os.path.exists(path):
                os.remove(path)
        if len(temp_paths) > 1 and 'merged_path' in locals() and os.path.exists(merged_path):
            os.remove(merged_path)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to process files: {str(e)}")
