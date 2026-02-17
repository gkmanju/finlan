"""
Utility for merging multiple files (PDFs and images) into a single PDF
"""
import os
from typing import List
from pypdf import PdfWriter, PdfReader
from PIL import Image
import io


def merge_files_to_pdf(file_paths: List[str], output_path: str) -> str:
    """
    Merge multiple files (PDFs and images) into a single PDF.
    
    Args:
        file_paths: List of absolute paths to files to merge
        output_path: Absolute path where merged PDF should be saved
        
    Returns:
        Path to the merged PDF file
    """
    writer = PdfWriter()
    
    for file_path in file_paths:
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext == '.pdf':
            # Add PDF pages
            reader = PdfReader(file_path)
            for page in reader.pages:
                writer.add_page(page)
                
        elif ext in ['.jpg', '.jpeg', '.png']:
            # Convert image to PDF and add
            img = Image.open(file_path)
            
            # Convert to RGB if necessary (for PNG with transparency)
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Save image to temporary PDF bytes
            img_bytes = io.BytesIO()
            img.save(img_bytes, format='PDF')
            img_bytes.seek(0)
            
            # Add to merged PDF
            img_reader = PdfReader(img_bytes)
            for page in img_reader.pages:
                writer.add_page(page)
        else:
            raise ValueError(f"Unsupported file type: {ext}")
    
    # Write merged PDF
    with open(output_path, 'wb') as output_file:
        writer.write(output_file)
    
    return output_path
