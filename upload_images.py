#!/usr/bin/env python3
"""
DigitalOcean Spaces Image Uploader
Uploads images in original and thumbnail versions to DigitalOcean Spaces.
"""

import os
import sys
import argparse
import mimetypes
from pathlib import Path
from typing import List, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv
from PIL import Image
from tqdm import tqdm
import io
import logging
from datetime import datetime
import threading

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'upload_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Supported image extensions
SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tiff', '.tif'}

# Thumbnail configuration
THUMBNAIL_WIDTH = 200
THUMBNAIL_HEIGHT = 300  # 2:3 ratio


class ImageUploader:
    """Handles image processing and uploading to DigitalOcean Spaces."""
    
    def __init__(self, folder_prefix: str = "avatar"):
        """Initialize the uploader with credentials from .env file."""
        load_dotenv()
        
        # Validate required environment variables
        required_vars = ['SPACES_ACCESS_KEY', 'SPACES_SECRET_KEY', 'SPACES_BUCKET', 
                        'SPACES_REGION', 'SPACES_ENDPOINT']
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
        
        # Initialize S3 client for DigitalOcean Spaces
        self.s3_client = boto3.client(
            's3',
            endpoint_url=os.getenv('SPACES_ENDPOINT'),
            aws_access_key_id=os.getenv('SPACES_ACCESS_KEY'),
            aws_secret_access_key=os.getenv('SPACES_SECRET_KEY'),
            region_name=os.getenv('SPACES_REGION')
        )
        
        self.bucket_name = os.getenv('SPACES_BUCKET')
        self.acl = os.getenv('SPACES_ACL', 'public-read')
        self.folder_prefix = folder_prefix
        
        # Statistics with thread lock
        self.stats = {
            'total_files': 0,
            'successful_uploads': 0,
            'failed_uploads': 0,
            'skipped_files': 0
        }
        self.stats_lock = threading.Lock()
        
        logger.info(f"Initialized uploader for bucket: {self.bucket_name}")
        logger.info(f"Folder prefix: {self.folder_prefix}")
    
    def get_image_files(self, directory: str) -> List[Path]:
        """
        Scan directory recursively for image files.
        
        Args:
            directory: Path to the directory containing images
            
        Returns:
            List of Path objects for image files
        """
        image_files = []
        directory_path = Path(directory)
        
        if not directory_path.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
        
        for file_path in directory_path.rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                image_files.append(file_path)
        
        logger.info(f"Found {len(image_files)} image files in {directory}")
        return sorted(image_files)
    
    def create_thumbnail(self, image_path: Path) -> Optional[io.BytesIO]:
        """
        Create a thumbnail from an image with 200x300px dimensions (2:3 ratio).
        The image is scaled and center-cropped to completely fill the dimensions.
        
        Args:
            image_path: Path to the original image
            
        Returns:
            BytesIO object containing the thumbnail image data, or None if failed
        """
        try:
            with Image.open(image_path) as img:
                # Convert RGBA to RGB if necessary
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Calculate dimensions for cover (fill) mode - scale to cover entire thumbnail
                original_width, original_height = img.size
                aspect_ratio = original_width / original_height
                target_ratio = THUMBNAIL_WIDTH / THUMBNAIL_HEIGHT
                
                if aspect_ratio > target_ratio:
                    # Image is wider - scale to fit height, then crop width
                    new_height = THUMBNAIL_HEIGHT
                    new_width = int(THUMBNAIL_HEIGHT * aspect_ratio)
                else:
                    # Image is taller - scale to fit width, then crop height
                    new_width = THUMBNAIL_WIDTH
                    new_height = int(THUMBNAIL_WIDTH / aspect_ratio)
                
                # Resize image with high-quality resampling
                img_resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # Calculate crop box to center the image
                left = (new_width - THUMBNAIL_WIDTH) // 2
                top = (new_height - THUMBNAIL_HEIGHT) // 2
                right = left + THUMBNAIL_WIDTH
                bottom = top + THUMBNAIL_HEIGHT
                
                # Crop to exact dimensions
                thumbnail = img_resized.crop((left, top, right, bottom))
                
                # Save to BytesIO
                output = io.BytesIO()
                thumbnail.save(output, format='JPEG', quality=85, optimize=True)
                output.seek(0)
                
                return output
        
        except Exception as e:
            logger.error(f"Failed to create thumbnail for {image_path}: {str(e)}")
            return None
    
    def get_content_type(self, file_path: Path) -> str:
        """
        Determine the MIME type of a file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            MIME type string
        """
        content_type, _ = mimetypes.guess_type(str(file_path))
        return content_type or 'application/octet-stream'
    
    def file_exists_in_spaces(self, key: str) -> bool:
        """
        Check if a file already exists in Spaces.
        
        Args:
            key: The object key in Spaces
            
        Returns:
            True if file exists, False otherwise
        """
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except ClientError:
            return False
    
    def upload_file(self, file_data: io.BytesIO, key: str, content_type: str, 
                   retry_count: int = 3) -> bool:
        """
        Upload a file to DigitalOcean Spaces with retry logic.
        
        Args:
            file_data: BytesIO object or file path
            key: The object key (path) in Spaces
            content_type: MIME type of the file
            retry_count: Number of retry attempts
            
        Returns:
            True if upload successful, False otherwise
        """
        for attempt in range(retry_count):
            try:
                if isinstance(file_data, io.BytesIO):
                    file_data.seek(0)
                    self.s3_client.put_object(
                        Bucket=self.bucket_name,
                        Key=key,
                        Body=file_data,
                        ContentType=content_type,
                        ACL=self.acl
                    )
                else:
                    with open(file_data, 'rb') as f:
                        self.s3_client.put_object(
                            Bucket=self.bucket_name,
                            Key=key,
                            Body=f,
                            ContentType=content_type,
                            ACL=self.acl
                        )
                return True
            
            except ClientError as e:
                if attempt < retry_count - 1:
                    logger.warning(f"Upload attempt {attempt + 1} failed for {key}, retrying...")
                else:
                    logger.error(f"Failed to upload {key} after {retry_count} attempts: {str(e)}")
                    return False
            except Exception as e:
                logger.error(f"Unexpected error uploading {key}: {str(e)}")
                return False
        
        return False
    
    def process_and_upload_image(self, image_path: Path, base_dir: Path, 
                                skip_existing: bool = True) -> Tuple[bool, bool]:
        """
        Process an image and upload both original and thumbnail versions.
        
        Args:
            image_path: Path to the image file
            base_dir: Base directory for calculating relative paths
            skip_existing: Whether to skip files that already exist in Spaces
            
        Returns:
            Tuple of (original_success, thumbnail_success)
        """
        # Calculate relative path from base directory
        relative_path = image_path.relative_to(base_dir)
        
        # Define keys for original and thumbnail with folder prefix
        original_key = f"{self.folder_prefix}/original/{relative_path.as_posix()}"
        thumbnail_key = f"{self.folder_prefix}/thumbnail/{relative_path.as_posix()}"
        
        original_success = False
        thumbnail_success = False
        
        # Check if files already exist
        original_exists = False
        thumbnail_exists = False
        
        if skip_existing:
            original_exists = self.file_exists_in_spaces(original_key)
            thumbnail_exists = self.file_exists_in_spaces(thumbnail_key)
            
            if original_exists and thumbnail_exists:
                logger.debug(f"Skipping {relative_path} - already uploaded")
                with self.stats_lock:
                    self.stats['skipped_files'] += 1
                return (True, True)
        
        # Get content type
        content_type = self.get_content_type(image_path)
        
        # Upload original
        if not skip_existing or not original_exists:
            original_success = self.upload_file(image_path, original_key, content_type)
            if original_success:
                logger.debug(f"Uploaded original: {original_key}")
        else:
            original_success = True
        
        # Create and upload thumbnail
        if not skip_existing or not thumbnail_exists:
            thumbnail_data = self.create_thumbnail(image_path)
            if thumbnail_data:
                thumbnail_success = self.upload_file(
                    thumbnail_data, 
                    thumbnail_key, 
                    'image/jpeg'
                )
                if thumbnail_success:
                    logger.debug(f"Uploaded thumbnail: {thumbnail_key}")
            else:
                logger.error(f"Failed to create thumbnail for {relative_path}")
        else:
            thumbnail_success = True
        
        return (original_success, thumbnail_success)
    
    def upload_directory(self, directory: str, skip_existing: bool = True, 
                        workers: int = 1, batch_size: int = 100):
        """
        Upload all images from a directory to DigitalOcean Spaces.
        
        Args:
            directory: Path to the directory containing images
            skip_existing: Whether to skip files that already exist in Spaces
            workers: Number of concurrent upload threads (1 = sequential, >1 = parallel)
            batch_size: Number of files to process in each batch
        """
        logger.info(f"Starting upload from directory: {directory}")
        logger.info(f"Skip existing files: {skip_existing}")
        logger.info(f"Concurrent workers: {workers}")
        
        # Get all image files
        image_files = self.get_image_files(directory)
        self.stats['total_files'] = len(image_files)
        
        if not image_files:
            logger.warning("No image files found to upload")
            return
        
        base_dir = Path(directory)
        
        if workers == 1:
            # Sequential processing
            self._upload_sequential(image_files, base_dir, skip_existing)
        else:
            # Concurrent processing
            self._upload_concurrent(image_files, base_dir, skip_existing, workers, batch_size)
        
        # Print summary
        self.print_summary()
    
    def _upload_sequential(self, image_files: List[Path], base_dir: Path, 
                          skip_existing: bool):
        """Upload images sequentially (one at a time)."""
        with tqdm(total=len(image_files), desc="Uploading images", unit="file") as pbar:
            for image_path in image_files:
                try:
                    original_success, thumbnail_success = self.process_and_upload_image(
                        image_path, base_dir, skip_existing
                    )
                    
                    if original_success and thumbnail_success:
                        with self.stats_lock:
                            self.stats['successful_uploads'] += 1
                    else:
                        with self.stats_lock:
                            self.stats['failed_uploads'] += 1
                        logger.error(f"Failed to fully upload: {image_path.name}")
                
                except Exception as e:
                    with self.stats_lock:
                        self.stats['failed_uploads'] += 1
                    logger.error(f"Error processing {image_path}: {str(e)}")
                
                pbar.update(1)
    
    def _upload_concurrent(self, image_files: List[Path], base_dir: Path, 
                          skip_existing: bool, workers: int, batch_size: int):
        """Upload images concurrently using multiple threads."""
        logger.info(f"Processing {len(image_files)} files with {workers} workers in batches of {batch_size}")
        
        # Process in batches to avoid overwhelming the system
        for batch_start in range(0, len(image_files), batch_size):
            batch_end = min(batch_start + batch_size, len(image_files))
            batch = image_files[batch_start:batch_end]
            
            logger.info(f"Processing batch {batch_start//batch_size + 1} "
                       f"({batch_start + 1}-{batch_end} of {len(image_files)})")
            
            with tqdm(total=len(batch), desc=f"Batch {batch_start//batch_size + 1}", unit="file") as pbar:
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    # Submit all tasks
                    future_to_path = {
                        executor.submit(
                            self.process_and_upload_image, 
                            image_path, 
                            base_dir, 
                            skip_existing
                        ): image_path
                        for image_path in batch
                    }
                    
                    # Process completed tasks
                    for future in as_completed(future_to_path):
                        image_path = future_to_path[future]
                        try:
                            original_success, thumbnail_success = future.result()
                            
                            if original_success and thumbnail_success:
                                with self.stats_lock:
                                    self.stats['successful_uploads'] += 1
                            else:
                                with self.stats_lock:
                                    self.stats['failed_uploads'] += 1
                                logger.error(f"Failed to fully upload: {image_path.name}")
                        
                        except Exception as e:
                            with self.stats_lock:
                                self.stats['failed_uploads'] += 1
                            logger.error(f"Error processing {image_path}: {str(e)}")
                        
                        pbar.update(1)
    
    def print_summary(self):
        """Print upload summary statistics."""
        logger.info("\n" + "="*60)
        logger.info("UPLOAD SUMMARY")
        logger.info("="*60)
        logger.info(f"Total files found:      {self.stats['total_files']}")
        logger.info(f"Successfully uploaded:  {self.stats['successful_uploads']}")
        logger.info(f"Failed uploads:         {self.stats['failed_uploads']}")
        logger.info(f"Skipped (existing):     {self.stats['skipped_files']}")
        logger.info("="*60)


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description='Upload images to DigitalOcean Spaces in original and thumbnail versions.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Sequential upload (safe, slower)
  python upload_images.py /path/to/images
  
  # Batch upload with 10 concurrent workers (much faster for thousands of images)
  python upload_images.py /path/to/images --workers 10
  
  # Upload to custom folder prefix
  python upload_images.py /path/to/images --prefix profile
  
  # Force re-upload all files
  python upload_images.py /path/to/images --no-skip-existing
  
  # Combine options for maximum speed
  python upload_images.py /path/to/images --workers 20 --batch-size 200
        """
    )
    
    parser.add_argument(
        'directory',
        help='Path to the directory containing images to upload'
    )
    
    parser.add_argument(
        '--workers',
        type=int,
        default=1,
        help='Number of concurrent upload threads (default: 1 = sequential). '
             'Recommended: 10-20 for thousands of images'
    )
    
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Number of files to process in each batch (default: 100). '
             'Only applies when using multiple workers'
    )
    
    parser.add_argument(
        '--prefix',
        type=str,
        default='avatar',
        help='Folder prefix in the bucket (default: avatar). '
             'Files will be uploaded to /<prefix>/original/ and /<prefix>/thumbnail/'
    )
    
    parser.add_argument(
        '--no-skip-existing',
        action='store_true',
        help='Upload all files even if they already exist in Spaces (default: skip existing)'
    )
    
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    
    args = parser.parse_args()
    
    # Set debug level if requested
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Validate workers count
    if args.workers < 1:
        logger.error("Workers must be at least 1")
        sys.exit(1)
    
    if args.workers > 50:
        logger.warning("Using more than 50 workers may cause rate limiting or connection issues")
    
    try:
        # Initialize uploader
        uploader = ImageUploader(folder_prefix=args.prefix)
        
        # Upload directory
        uploader.upload_directory(
            args.directory,
            skip_existing=not args.no_skip_existing,
            workers=args.workers,
            batch_size=args.batch_size
        )
        
    except ValueError as e:
        logger.error(f"Configuration error: {str(e)}")
        logger.error("Please check your .env file and ensure all required variables are set.")
        sys.exit(1)
    
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    
    except NoCredentialsError:
        logger.error("Failed to authenticate with DigitalOcean Spaces.")
        logger.error("Please check your credentials in the .env file.")
        sys.exit(1)
    
    except KeyboardInterrupt:
        logger.info("\nUpload interrupted by user.")
        sys.exit(0)
    
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()

