"""
Form Extractor - Extracts all forms and their fields for testing.
"""

from dataclasses import dataclass, field
from typing import Optional

from bs4 import BeautifulSoup
from loguru import logger


@dataclass
class FormField:
    """Represents a form field."""
    name: str
    field_type: str  # text, password, email, hidden, etc.
    value: Optional[str] = None
    required: bool = False
    placeholder: Optional[str] = None
    pattern: Optional[str] = None
    min_length: Optional[int] = None
    max_length: Optional[int] = None


@dataclass
class Form:
    """Represents an HTML form."""
    action: str
    method: str
    fields: list[FormField] = field(default_factory=list)
    has_file_upload: bool = False
    has_csrf_token: bool = False
    form_id: Optional[str] = None
    form_name: Optional[str] = None
    enctype: Optional[str] = None


class FormExtractor:
    """
    Extracts forms from HTML pages.
    
    Identifies:
    - All form fields and their types
    - File upload forms
    - CSRF tokens
    - Required fields
    - Validation patterns
    """
    
    def __init__(self):
        """Initialize form extractor."""
        self.csrf_indicators = {'csrf', 'token', '_token', 'authenticity', 'nonce'}
    
    def extract_forms(self, html: str, base_url: str) -> list[Form]:
        """
        Extract all forms from HTML.
        
        Args:
            html: HTML content
            base_url: Base URL for resolving relative actions
            
        Returns:
            List of extracted forms
        """
        soup = BeautifulSoup(html, 'html.parser')
        forms = []
        
        for form_tag in soup.find_all('form'):
            form = self._parse_form(form_tag, base_url)
            forms.append(form)
        
        logger.debug(f"Extracted {len(forms)} forms")
        
        return forms
    
    def _parse_form(self, form_tag, base_url: str) -> Form:
        """Parse a single form tag."""
        from urllib.parse import urljoin
        
        # Extract form attributes
        action = form_tag.get('action', '')
        if action:
            action = urljoin(base_url, action)
        else:
            action = base_url
        
        method = form_tag.get('method', 'GET').upper()
        form_id = form_tag.get('id')
        form_name = form_tag.get('name')
        enctype = form_tag.get('enctype')
        
        # Extract fields
        fields = []
        has_file_upload = False
        has_csrf_token = False
        
        # Find all input, textarea, select elements
        for input_tag in form_tag.find_all(['input', 'textarea', 'select']):
            field = self._parse_field(input_tag)
            
            if field:
                fields.append(field)
                
                # Check for file upload
                if field.field_type == 'file':
                    has_file_upload = True
                
                # Check for CSRF token
                if any(indicator in field.name.lower() for indicator in self.csrf_indicators):
                    has_csrf_token = True
        
        return Form(
            action=action,
            method=method,
            fields=fields,
            has_file_upload=has_file_upload,
            has_csrf_token=has_csrf_token,
            form_id=form_id,
            form_name=form_name,
            enctype=enctype,
        )
    
    def _parse_field(self, tag) -> Optional[FormField]:
        """Parse a single form field."""
        name = tag.get('name')
        if not name:
            return None
        
        # Get field type
        if tag.name == 'input':
            field_type = tag.get('type', 'text')
        elif tag.name == 'textarea':
            field_type = 'textarea'
        elif tag.name == 'select':
            field_type = 'select'
        else:
            field_type = 'unknown'
        
        # Extract attributes
        value = tag.get('value')
        required = tag.has_attr('required')
        placeholder = tag.get('placeholder')
        pattern = tag.get('pattern')
        
        min_length = None
        max_length = None
        
        if tag.has_attr('minlength'):
            try:
                min_length = int(tag.get('minlength'))
            except ValueError:
                pass
        
        if tag.has_attr('maxlength'):
            try:
                max_length = int(tag.get('maxlength'))
            except ValueError:
                pass
        
        return FormField(
            name=name,
            field_type=field_type,
            value=value,
            required=required,
            placeholder=placeholder,
            pattern=pattern,
            min_length=min_length,
            max_length=max_length,
        )
    
    def get_form_summary(self, forms: list[Form]) -> dict:
        """Get summary statistics about extracted forms."""
        return {
            "total_forms": len(forms),
            "forms_with_file_upload": sum(1 for f in forms if f.has_file_upload),
            "forms_with_csrf": sum(1 for f in forms if f.has_csrf_token),
            "post_forms": sum(1 for f in forms if f.method == "POST"),
            "get_forms": sum(1 for f in forms if f.method == "GET"),
            "total_fields": sum(len(f.fields) for f in forms),
        }
