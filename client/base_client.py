import requests
import time
import os
from typing import Optional, Dict, Any
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class AnyToMdClient:
    """Client for Document to Markdown Converter API."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        """
        Initialize client.
        
        Args:
            base_url: Base URL of the API service
        """
        self.base_url = base_url.rstrip('/')
        self.api_base = f"{self.base_url}/api/v1"
        
    def convert_file(self, file_path: str, type_result: str = None) -> Dict[str, Any]:
        """
        Submit a file for conversion.
        
        Args:
            file_path: Path to the file to convert
            type_result: Optional. Controls what's included in the result ZIP:
                        - "norm" (default): Only markdown file
                        - "test": Markdown + extracted images (for verification)
                        Note: Images are always uploaded to S3 in both modes
            
        Returns:
            Response with task_id and status
            
        Raises:
            requests.HTTPError: If the request fails
            FileNotFoundError: If the file doesn't exist
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        with open(file_path, 'rb') as f:
            files = {'file': (os.path.basename(file_path), f)}
            data = {}
            if type_result is not None:
                data['type_result'] = type_result
            response = requests.post(f"{self.api_base}/convert", files=files, data=data if data else None)
        
        response.raise_for_status()
        return response.json()
    
    def check_status(self, task_id: str) -> Dict[str, Any]:
        """
        Check conversion task status.
        
        Args:
            task_id: Task ID from convert_file response
            
        Returns:
            Task status information
        """
        response = requests.get(f"{self.api_base}/task/{task_id}")
        response.raise_for_status()
        return response.json()
    
    def download_result(self, task_id: str, output_path: Optional[str] = None) -> str:
        """
        Download conversion result.
        
        Args:
            task_id: Task ID
            output_path: Where to save the file (optional)
            
        Returns:
            Path to the downloaded file
        """
        response = requests.get(f"{self.api_base}/download/{task_id}", stream=True)
        response.raise_for_status()
        
        # Get filename from headers or use default
        filename = "result.zip"
        if 'content-disposition' in response.headers:
            cd = response.headers['content-disposition']
            if 'filename=' in cd:
                filename = cd.split('filename=')[1].strip('"')
        
        if output_path:
            save_path = output_path
        else:
            save_path = filename
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        
        # Save file
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return save_path
    
    def convert_and_wait(
        self, 
        file_path: str, 
        output_path: Optional[str] = None,
        poll_interval: float = 1.0,
        timeout: float = 300.0,
        type_result: str = None
    ) -> str:
        """
        Convert a file and wait for completion.
        
        Args:
            file_path: Path to file to convert
            output_path: Where to save result (optional)
            poll_interval: How often to check status (seconds)
            timeout: Maximum time to wait (seconds)
            type_result: Optional. Controls what's included in the result ZIP:
                        - "norm" (default): Only markdown file
                        - "test": Markdown + extracted images (for verification)
                        Note: Images are always uploaded to S3 in both modes
            
        Returns:
            Path to downloaded result
            
        Raises:
            TimeoutError: If conversion takes too long
            RuntimeError: If conversion fails
        """
        # Submit file
        logger.info(f"Submitting {file_path} for conversion")
        result = self.convert_file(file_path, type_result=type_result)
        task_id = result['task_id']
        
        # Wait for completion
        start_time = time.time()
        while True:
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Conversion timeout after {timeout} seconds")
            
            status = self.check_status(task_id)
            logger.info(f"Task {task_id}: {status['status']} ({status['progress']}%)")
            
            if status['status'] == 'completed':
                break
            elif status['status'] == 'failed':
                raise RuntimeError(f"Conversion failed: {status.get('message', 'Unknown error')}")
            
            time.sleep(poll_interval)
        
        # Download result
        logger.info(f"Downloading result for task {task_id}")
        return self.download_result(task_id, output_path)
    
    def get_supported_formats(self) -> Dict[str, Any]:
        """Get list of supported formats."""
        response = requests.get(f"{self.api_base}/formats")
        response.raise_for_status()
        return response.json()
    
    def get_pending_tasks(self) -> Dict[str, Any]:
        """Get list of pending tasks."""
        response = requests.get(f"{self.api_base}/tasks/pending")
        response.raise_for_status()
        return response.json()
    
    def health_check(self) -> bool:
        """Check if service is healthy."""
        try:
            response = requests.get(f"{self.api_base}/health")
            response.raise_for_status()
            return response.json().get('status') == 'healthy'
        except:
            return False