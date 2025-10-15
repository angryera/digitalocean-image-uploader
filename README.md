# DigitalOcean Spaces Image Uploader

A Python script to upload thousands of images to DigitalOcean Spaces object storage in two versions:
- **Original** - Full-size original images
- **Thumbnail** - 200x300px (2:3 ratio) optimized thumbnails

## Features

- 🚀 **Concurrent batch uploading** - Upload with multiple threads (10-20x faster for thousands of images!)
- 📦 Batch upload thousands of images efficiently
- 🖼️ Automatic thumbnail generation (200x300px, 2:3 ratio, center-cropped to fill completely)
- 📁 Organized storage with separate folders for originals and thumbnails
- ⏭️ Skip already uploaded files (resume capability)
- 🔄 Automatic retry logic for failed uploads
- 📊 Progress tracking with visual progress bar
- 📝 Detailed logging to file and console
- 🎨 Supports multiple image formats (JPG, PNG, WebP, GIF, BMP, TIFF)
- ⚙️ Configurable folder structure (default: `/avatar/original/` and `/avatar/thumbnail/`)

## Prerequisites

- Python 3.7 or higher
- DigitalOcean Spaces account with a bucket created
- Access key and secret key for your Spaces bucket

## Installation

1. **Clone or download this repository**

2. **Install dependencies**

```bash
pip install -r requirements.txt
```

3. **Configure credentials**

Copy the `.env.example` file to `.env`:

```bash
cp .env.example .env
```

Edit the `.env` file and add your DigitalOcean Spaces credentials:

```env
SPACES_ACCESS_KEY=your_access_key_here
SPACES_SECRET_KEY=your_secret_key_here
SPACES_BUCKET=your_bucket_name
SPACES_REGION=nyc3
SPACES_ENDPOINT=https://nyc3.digitaloceanspaces.com
SPACES_ACL=public-read
```

### Getting Your Credentials

1. Log in to your DigitalOcean account
2. Go to **API** → **Spaces Keys**
3. Generate a new key pair (Access Key and Secret Key)
4. Note your bucket name and region

### Common Regions and Endpoints

| Region | Endpoint |
|--------|----------|
| NYC3 | `https://nyc3.digitaloceanspaces.com` |
| SFO2 | `https://sfo2.digitaloceanspaces.com` |
| SFO3 | `https://sfo3.digitaloceanspaces.com` |
| AMS3 | `https://ams3.digitaloceanspaces.com` |
| SGP1 | `https://sgp1.digitaloceanspaces.com` |
| FRA1 | `https://fra1.digitaloceanspaces.com` |

## Usage

### Basic Usage

**Sequential upload (safe, but slower):**

```bash
python upload_images.py /path/to/your/images
```

### Batch Upload (Recommended for Thousands of Images)

**Upload with 10 concurrent workers (10-20x faster!):**

```bash
python upload_images.py /path/to/your/images --workers 10
```

**Upload with 20 workers for maximum speed:**

```bash
python upload_images.py /path/to/your/images --workers 20 --batch-size 200
```

### Advanced Options

**Upload to a custom folder prefix:**

```bash
python upload_images.py /path/to/your/images --prefix profile
# This will upload to /profile/original/ and /profile/thumbnail/
```

**Upload without skipping existing files:**

```bash
python upload_images.py /path/to/your/images --no-skip-existing
```

**Enable debug logging:**

```bash
python upload_images.py /path/to/your/images --debug
```

**Combine multiple options:**

```bash
python upload_images.py /path/to/your/images --workers 15 --prefix avatar --debug
```

### Available Options

- `--workers N` - Number of concurrent upload threads (default: 1). Recommended: 10-20 for thousands of images
- `--batch-size N` - Number of files per batch (default: 100). Only applies with multiple workers
- `--prefix NAME` - Folder prefix in bucket (default: "avatar")
- `--no-skip-existing` - Re-upload files even if they already exist
- `--debug` - Enable detailed debug logging

### Help

```bash
python upload_images.py --help
```

## How It Works

1. **Scanning**: The script recursively scans the specified directory for supported image files
2. **Processing**: For each image:
   - Uploads the original to `/avatar/original/` folder in your bucket (customizable)
   - Creates a 200x300px thumbnail (scaled and center-cropped to fill completely, no empty spaces)
   - Uploads the thumbnail to `/avatar/thumbnail/` folder in your bucket (customizable)
3. **Concurrency**: With `--workers` option, processes multiple images simultaneously
4. **Progress**: Shows a progress bar and logs all operations
5. **Resume**: By default, skips files that already exist in Spaces (can be overridden)
6. **Summary**: Displays statistics at the end

## Folder Structure in Spaces

After uploading with default settings, your bucket will have this structure:

```
your-bucket/
└── avatar/
    ├── original/
    │   ├── image1.jpg
    │   ├── image2.png
    │   └── subfolder/
    │       └── image3.jpg
    └── thumbnail/
        ├── image1.jpg
        ├── image2.jpg
        └── subfolder/
            └── image3.jpg
```

**Customizable Folder Structure:**

You can change the folder prefix using `--prefix`. For example, `--prefix profile` will create:

```
your-bucket/
└── profile/
    ├── original/
    └── thumbnail/
```

The script preserves the relative directory structure from your source folder.

## Thumbnail Details

- **Width**: 200px
- **Height**: 300px (2:3 ratio)
- **Format**: JPEG (for compatibility and size optimization)
- **Quality**: 85% (good balance between quality and file size)
- **Cropping**: Center-cropped to fill dimensions completely (no empty spaces)
- **Resampling**: LANCZOS (high-quality downscaling)

## Logging

Logs are written to both:
- **Console**: Real-time progress and important messages
- **Log file**: Detailed log with timestamp (e.g., `upload_log_20231015_143022.log`)

## Error Handling

- Failed uploads are automatically retried up to 3 times
- Corrupted or unreadable images are skipped with error logging
- Network errors are handled gracefully with retry logic
- The script can be safely interrupted (Ctrl+C) and resumed later

## Supported Image Formats

- JPEG (.jpg, .jpeg)
- PNG (.png)
- WebP (.webp)
- GIF (.gif)
- BMP (.bmp)
- TIFF (.tiff, .tif)

## Troubleshooting

### "Missing required environment variables"

Make sure your `.env` file exists and contains all required variables. Check that you've copied `.env.example` to `.env` and filled in your credentials.

### "Failed to authenticate with DigitalOcean Spaces"

Verify your access key and secret key are correct. Make sure your key has permissions to write to the bucket.

### "Directory not found"

Ensure the path to your images directory is correct. Use absolute paths if relative paths aren't working.

### Slow uploads

- Check your internet connection speed
- DigitalOcean Spaces has rate limits; very large batches might be throttled
- Consider running the script during off-peak hours for better performance

## Security Notes

- Never commit your `.env` file to version control
- The `.gitignore` file should include `.env`
- Keep your access keys secure and rotate them periodically
- Consider using `SPACES_ACL=private` if files should not be publicly accessible

## Performance

### Sequential Mode (--workers 1, default)
- Safest option, processes one image at a time
- Approximately 2-5 seconds per image (including upload time)
- Good for small batches or slower internet connections

### Concurrent Mode (--workers 10-20, recommended)
- **10-20x faster** for large batches
- Processes multiple images simultaneously
- Recommended settings:
  - **10 workers**: Good balance of speed and stability
  - **15-20 workers**: Maximum speed for thousands of images
  - **Batch size 100-200**: Optimal for memory management
- Already uploaded files are skipped quickly (only a HEAD request is made)

### Performance Tips
- Start with `--workers 10` and increase if your network can handle it
- Monitor your internet upload speed - more workers help if you have bandwidth
- DigitalOcean Spaces can handle high concurrency well
- Use `--debug` to see detailed timing information

### Example Performance
- **1,000 images** with sequential: ~60-80 minutes
- **1,000 images** with 10 workers: ~6-8 minutes
- **1,000 images** with 20 workers: ~3-5 minutes

## License

This script is provided as-is for use with DigitalOcean Spaces.

