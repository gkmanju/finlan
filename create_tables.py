#!/usr/bin/env python
from app.database import Base, engine
from app.models import BrokerCredential

Base.metadata.create_all(bind=engine)
print("Database tables created successfully")
