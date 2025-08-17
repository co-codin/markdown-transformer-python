# S3 Integration for any_to_md

## Overview

The any_to_md service supports optional S3 integration for storing conversion results. When enabled, the complete ZIP archive with converted Markdown and images is uploaded to Amazon S3.

## Important Changes

**❗ NEW**: Starting from version 2.0, when S3 is enabled:
- The entire ZIP archive is uploaded to S3 (not individual files)
- The `/download` endpoint returns a text file containing the S3 URL (not the ZIP itself)
- Clients must download the ZIP directly from the S3 URL

## Benefits

1. **Reduced server load** - Files are served directly from S3
2. **Direct URLs** - Markdown files contain publicly accessible image URLs
3. **Scalability** - S3 handles any amount of data
4. **CDN ready** - S3 URLs work with CloudFront and other CDNs

## Setup

### 1. Install boto3

```bash
pip install boto3
```

### 2. Create S3 Bucket

1. Log in to AWS Console
2. Go to S3 service
3. Create a new bucket
4. Enable public access for images (Block public access = OFF)
5. Add bucket policy for public read:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "PublicReadGetObject",
            "Effect": "Allow",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::your-bucket-name/markdown-images/*"
        }
    ]
}
```

### 3. Create IAM User

1. Go to IAM service
2. Create new user with programmatic access
3. Attach policy: `AmazonS3FullAccess` (or custom policy with PutObject permission)
4. Save Access Key and Secret Key

### 4. Configure Environment Variables

```bash
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
export AWS_STORAGE_BUCKET_NAME="your-bucket-name"
export AWS_S3_REGION_NAME="us-east-1"  # optional, default: us-east-1
export S3_FOLDER_PREFIX="markdown-images"  # optional, default: markdown-images
```

Or create `.env` file:

```env
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_STORAGE_BUCKET_NAME=your-bucket-name
AWS_S3_REGION_NAME=us-east-1
S3_FOLDER_PREFIX=markdown-images
```

### 5. Restart Service

```bash
# Local
python app/main.py

# Docker
docker-compose restart
```

## How It Works

When S3 is configured:

1. Document is converted to markdown as usual
2. All extracted images are uploaded to S3
3. Image paths in markdown are replaced with S3 URLs
4. Original local images are kept as backup

### Example

Before (local images):
```markdown
![Figure 1](./images/figure1.png)
![Chart](./images/chart.jpg)
```

After (S3 URLs):
```markdown
![Figure 1](https://your-bucket.s3.us-east-1.amazonaws.com/markdown-images/task-id/figure1_a3f2d1.png)
![Chart](https://your-bucket.s3.us-east-1.amazonaws.com/markdown-images/task-id/chart_b4e5c2.jpg)
```

## API Response

When S3 is enabled, the API response includes S3 information:

```json
{
  "task_id": "abc123",
  "status": "COMPLETED",
  "result": {
    "markdown_file": "document.md",
    "images_uploaded": 5,
    "s3_enabled": true,
    "s3_bucket": "your-bucket-name"
  }
}
```

## Disabling S3

To disable S3 integration, simply remove the environment variables and restart the service. The service will revert to local image storage.

## Troubleshooting

### Images not uploading

1. Check AWS credentials are correct
2. Verify bucket exists and is accessible
3. Check bucket permissions allow PutObject
4. Look at service logs for specific errors

### Wrong region error

Make sure `AWS_S3_REGION_NAME` matches your bucket's region.

### Access denied errors

Verify IAM user has proper S3 permissions.

## Cost Considerations

- S3 storage: ~$0.023 per GB per month
- Data transfer: ~$0.09 per GB (after 1GB free tier)
- PUT requests: ~$0.005 per 1000 requests

For typical usage (converting documents with images), costs are minimal.