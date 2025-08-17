# Contributing to any-to-md

Thank you for your interest in contributing to any-to-md! This document provides guidelines for contributing to the project.

## 🚀 Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/yourusername/any-to-md.git`
3. Create a new branch: `git checkout -b feature/your-feature-name`
4. Make your changes
5. Test your changes thoroughly
6. Commit with clear messages
7. Push to your fork
8. Create a Pull Request

## 💻 Development Setup

### Prerequisites

- Python 3.11+
- Docker and Docker Compose (for testing)
- Pandoc installed locally
- Git

### Setting Up Development Environment

```bash
# Clone the repository
git clone https://github.com/yourusername/any-to-md.git
cd any-to-md

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install marker-pdf  # For enhanced PDF conversion (optional, downloads ~2GB models on first run)

# Copy environment configuration
cp .env.example .env

# Run the service locally
python app/main.py
```

## 📋 Code Style Guidelines

### Python Code Style

- Follow PEP 8 guidelines
- Use meaningful variable and function names
- Add type hints where possible
- Keep functions small and focused
- Document complex logic with comments

### Example:

```python
from typing import Optional, Dict, Any

async def convert_document(
    file_path: str,
    output_format: str = "markdown"
) -> Optional[Dict[str, Any]]:
    """
    Convert a document to the specified format.
    
    Args:
        file_path: Path to the input document
        output_format: Target format (default: markdown)
        
    Returns:
        Dictionary with conversion results or None if failed
    """
    # Implementation here
    pass
```

### Commit Messages

- Use clear, descriptive commit messages
- Start with a verb in present tense
- Keep the first line under 50 characters
- Add detailed description if needed

Examples:
- `Add support for RTF format conversion`
- `Fix image extraction in PDF converter`
- `Update dependencies for security patches`

## 🧪 Testing

### Running Tests

```bash
# Test all formats
python test_scripts/test_all_formats.py

# Test specific converter
python test_scripts/test_single_file.py test_files/sample.pdf

# Test Docker build
docker build -t any-to-md:test .
python test_scripts/test_docker_all_formats.py
```

### Writing Tests

- Add test files to `test_files/` directory
- Create test scripts in `test_scripts/`
- Test both success and failure cases
- Verify image extraction works correctly

## 🔄 Pull Request Process

1. **Before Creating PR:**
   - Ensure all tests pass
   - Update documentation if needed
   - Add entry to CHANGELOG.md
   - Check no sensitive data is included

2. **PR Description Should Include:**
   - What changes were made
   - Why these changes are needed
   - How to test the changes
   - Any breaking changes

3. **PR Requirements:**
   - All tests must pass
   - Code follows project style
   - Documentation is updated
   - No merge conflicts

## 🐛 Reporting Issues

### Bug Reports

When reporting bugs, please include:

- Description of the issue
- Steps to reproduce
- Expected behavior
- Actual behavior
- System information (OS, Python version)
- Sample file (if applicable)
- Error messages/logs

### Feature Requests

For feature requests, please describe:

- The problem you're trying to solve
- Your proposed solution
- Alternative solutions considered
- Examples of usage

## 📁 Project Structure

```
any-to-md/
├── app/                 # Main application code
│   ├── api/            # API routes and schemas
│   ├── config/         # Configuration files
│   ├── converters/     # Document converters
│   └── utils/          # Utility functions
├── client/             # Python client library
├── test_files/         # Test documents
├── test_scripts/       # Testing scripts
└── docker/            # Docker-related files
```

## 🔒 Security

- Never commit sensitive data (API keys, passwords)
- Report security vulnerabilities privately
- Keep dependencies updated
- Follow secure coding practices

## 📚 Adding New Converters

To add support for a new format:

1. Create converter class in `app/converters/`
2. Inherit from `BaseConverter`
3. Implement `convert()` method
4. Add format to `SUPPORTED_FORMATS`
5. Add test files and scripts
6. Update documentation

Example:
```python
from app.converters.base import BaseConverter

class NewFormatConverter(BaseConverter):
    def __init__(self):
        self.supported_formats = ['new', 'format']
    
    async def convert(self, input_path: str, output_dir: str) -> str:
        # Implementation
        pass
```

## 🤝 Code of Conduct

- Be respectful and inclusive
- Welcome newcomers and help them
- Focus on constructive criticism
- Respect differing viewpoints
- Accept responsibility for mistakes

## 📞 Getting Help

- Check existing issues first
- Read the documentation
- Ask in discussions
- Contact maintainers if needed

## 🙏 Recognition

Contributors will be recognized in:
- CHANGELOG.md
- GitHub contributors page
- Project documentation

Thank you for contributing to any-to-md!