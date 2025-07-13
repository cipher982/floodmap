#!/usr/bin/env python3
"""
Simple script to run the server for development and testing.
"""

import os
import uvicorn

if __name__ == "__main__":
    # Set environment variables
    os.environ.setdefault("INPUT_DIR", "scratch/data_tampa")
    os.environ.setdefault("PROCESSED_DIR", "scratch/data_tampa_processed") 
    
    # Run the server
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5001,
        reload=False,
        log_level="info"
    )