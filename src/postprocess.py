"""
Post-processing module for recorded tests.
Extracts input values and allows users to convert them to variables.
"""

import re
import logging
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class InputType(str, Enum):
    """Types of detected inputs."""
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    EMAIL = "email"
    SELECT = "select"
    CLICK_TEXT = "click_text"
    UNKNOWN = "unknown"


@dataclass
class DetectedInput:
    """A detected input value from the recorded test."""
    line_number: int
    original_line: str
    value: str
    input_type: InputType
    selector: str
    action: str  # fill, click, select_option, etc.
    variable_name: Optional[str] = None
    new_value: Optional[str] = None
    
    @property
    def display_value(self) -> str:
        """Get the value to display (new or original)."""
        return self.new_value if self.new_value is not None else self.value
    
    @property
    def is_modified(self) -> bool:
        """Check if this input has been modified."""
        return self.variable_name is not None or self.new_value is not None


class TestAnalyzer:
    """
    Analyzes recorded test code to extract input values.
    """
    
    # Patterns to detect different Playwright actions with values
    PATTERNS = {
        'fill': [
            # page.fill("selector", "value")
            r'\.fill\s*\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)',
            # page.get_by_xxx().fill("value")
            r'\.get_by_\w+\([^)]*\)\.fill\s*\(\s*["\']([^"\']+)["\']\s*\)',
        ],
        'type': [
            r'\.type\s*\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']+)["\']\s*\)',
            r'\.get_by_\w+\([^)]*\)\.type\s*\(\s*["\']([^"\']+)["\']\s*\)',
        ],
        'press_sequentially': [
            r'\.press_sequentially\s*\(\s*["\']([^"\']+)["\']\s*\)',
        ],
        'select_option': [
            r'\.select_option\s*\(\s*["\']([^"\']+)["\']\s*\)',
            r'\.select_option\s*\(\s*\[([^\]]+)\]\s*\)',
        ],
        'click_text': [
            # page.get_by_text("some text").click()
            r'\.get_by_text\s*\(\s*["\']([^"\']+)["\']\s*\)\.click',
            # page.get_by_role("button", name="Submit").click()
            r'\.get_by_role\s*\(\s*["\'][^"\']+["\']\s*,\s*name\s*=\s*["\']([^"\']+)["\']\s*\)\.click',
        ],
        'check': [
            r'\.check\s*\(\s*\)',  # Just mark as checked action
        ],
        'goto': [
            r'\.goto\s*\(\s*["\']([^"\']+)["\']\s*\)',
        ],
    }
    
    # Patterns to detect value types
    DATE_PATTERNS = [
        r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
        r'\d{2}/\d{2}/\d{4}',  # DD/MM/YYYY or MM/DD/YYYY
        r'\d{2}-\d{2}-\d{4}',  # DD-MM-YYYY
    ]
    
    EMAIL_PATTERN = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
    NUMBER_PATTERN = r'^-?\d+\.?\d*$'
    
    def __init__(self, code: str):
        """
        Initialize analyzer with test code.
        
        Args:
            code: The recorded test code
        """
        self.code = code
        self.lines = code.split('\n')
        self._inputs: Optional[List[DetectedInput]] = None
    
    def _detect_input_type(self, value: str, selector: str = "") -> InputType:
        """Detect the type of input value."""
        # Check for date
        for pattern in self.DATE_PATTERNS:
            if re.match(pattern, value):
                return InputType.DATE
        
        # Check for email
        if re.match(self.EMAIL_PATTERN, value):
            return InputType.EMAIL
        
        # Check for number
        if re.match(self.NUMBER_PATTERN, value):
            return InputType.NUMBER
        
        # Check selector hints
        selector_lower = selector.lower()
        if any(hint in selector_lower for hint in ['email', 'mail']):
            return InputType.EMAIL
        if any(hint in selector_lower for hint in ['date', 'calendar']):
            return InputType.DATE
        if any(hint in selector_lower for hint in ['number', 'amount', 'quantity', 'qty', 'price']):
            return InputType.NUMBER
        
        return InputType.TEXT
    
    def _generate_variable_name(self, value: str, selector: str, action: str) -> str:
        """Generate a suggested variable name."""
        # Try to extract meaningful name from selector
        name_parts = []
        
        # Extract text from selector
        match = re.search(r'name[=:]?\s*["\']([^"\']+)["\']', selector, re.IGNORECASE)
        if match:
            name_parts.append(match.group(1))
        
        match = re.search(r'label[=:]?\s*["\']([^"\']+)["\']', selector, re.IGNORECASE)
        if match:
            name_parts.append(match.group(1))
        
        match = re.search(r'placeholder[=:]?\s*["\']([^"\']+)["\']', selector, re.IGNORECASE)
        if match:
            name_parts.append(match.group(1))
        
        # Extract ID or test-id
        match = re.search(r'(?:id|test-id|data-testid)[=:]?\s*["\']([^"\']+)["\']', selector, re.IGNORECASE)
        if match:
            name_parts.append(match.group(1))
        
        if name_parts:
            # Use first meaningful part
            name = name_parts[0]
        else:
            # Fall back to value-based name
            name = value[:20] if len(value) > 20 else value
        
        # Convert to valid variable name
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        name = re.sub(r'_+', '_', name)
        name = name.strip('_').upper()
        
        if not name or name[0].isdigit():
            name = f"INPUT_{name}" if name else "INPUT_VALUE"
        
        return name
    
    def analyze(self) -> List[DetectedInput]:
        """
        Analyze the test code and extract all input values.
        
        Returns:
            List of DetectedInput objects
        """
        if self._inputs is not None:
            return self._inputs
        
        self._inputs = []
        
        for line_num, line in enumerate(self.lines, start=1):
            stripped = line.strip()
            
            # Skip comments and empty lines
            if not stripped or stripped.startswith('#'):
                continue
            
            # Check each action type
            for action, patterns in self.PATTERNS.items():
                for pattern in patterns:
                    matches = re.finditer(pattern, line)
                    for match in matches:
                        groups = match.groups()
                        
                        if not groups:
                            continue
                        
                        # Extract value and selector based on pattern structure
                        if action in ('fill', 'type') and len(groups) >= 2:
                            selector = groups[0]
                            value = groups[1]
                        elif action in ('fill', 'type') and len(groups) == 1:
                            # get_by_xxx().fill() pattern
                            selector = self._extract_selector_from_line(line)
                            value = groups[0]
                        elif action == 'click_text':
                            selector = ""
                            value = groups[0]
                        elif action == 'goto':
                            selector = "page.goto"
                            value = groups[0]
                            # Skip the main URL (usually the D365 environment)
                            if 'dynamics' in value.lower() or 'microsoft' in value.lower():
                                continue
                        else:
                            selector = self._extract_selector_from_line(line)
                            value = groups[0] if groups else ""
                        
                        if not value:
                            continue
                        
                        # Detect input type
                        input_type = self._detect_input_type(value, selector)
                        if action == 'click_text':
                            input_type = InputType.CLICK_TEXT
                        elif action == 'select_option':
                            input_type = InputType.SELECT
                        
                        # Generate variable name
                        var_name = self._generate_variable_name(value, selector, action)
                        
                        detected = DetectedInput(
                            line_number=line_num,
                            original_line=line,
                            value=value,
                            input_type=input_type,
                            selector=selector,
                            action=action,
                            variable_name=None,  # Will be set by user
                            new_value=None
                        )
                        
                        # Store suggested name
                        detected._suggested_name = var_name
                        
                        self._inputs.append(detected)
        
        return self._inputs
    
    def _extract_selector_from_line(self, line: str) -> str:
        """Extract the selector portion from a line."""
        # Try to extract get_by_xxx portion
        match = re.search(r'(\.get_by_\w+\([^)]*\))', line)
        if match:
            return match.group(1)
        
        # Try to extract locator
        match = re.search(r'\.locator\s*\(\s*["\']([^"\']+)["\']\s*\)', line)
        if match:
            return match.group(1)
        
        return ""
    
    def get_suggested_variable_name(self, input_item: DetectedInput) -> str:
        """Get the suggested variable name for an input."""
        return getattr(input_item, '_suggested_name', 'INPUT_VALUE')


class TestModifier:
    """
    Modifies test code to use variables instead of hardcoded values.
    """
    
    def __init__(self, original_code: str):
        """
        Initialize modifier with original code.
        
        Args:
            original_code: The original test code
        """
        self.original_code = original_code
        self.lines = original_code.split('\n')
    
    def apply_modifications(
        self,
        inputs: List[DetectedInput]
    ) -> str:
        """
        Apply modifications to the test code.
        
        Args:
            inputs: List of DetectedInput objects with modifications
            
        Returns:
            Modified test code
        """
        modified_lines = self.lines.copy()
        variables = {}
        
        # Collect all variables
        for inp in inputs:
            if inp.variable_name:
                value = inp.new_value if inp.new_value else inp.value
                variables[inp.variable_name] = value
        
        # Apply line modifications
        for inp in inputs:
            if not inp.is_modified:
                continue
            
            line_idx = inp.line_number - 1
            if line_idx < 0 or line_idx >= len(modified_lines):
                continue
            
            original_line = modified_lines[line_idx]
            
            if inp.variable_name:
                # Replace value with variable reference
                new_value = f'get_var("{inp.variable_name}")'
                modified_line = original_line.replace(f'"{inp.value}"', new_value)
                modified_line = modified_line.replace(f"'{inp.value}'", new_value)
            elif inp.new_value:
                # Replace with new hardcoded value
                modified_line = original_line.replace(f'"{inp.value}"', f'"{inp.new_value}"')
                modified_line = modified_line.replace(f"'{inp.value}'", f"'{inp.new_value}'")
            else:
                modified_line = original_line
            
            modified_lines[line_idx] = modified_line
        
        # Update TEST_VARIABLES dict if there are variables
        if variables:
            modified_code = '\n'.join(modified_lines)
            modified_code = self._update_variables_dict(modified_code, variables)
            return modified_code
        
        return '\n'.join(modified_lines)
    
    def _update_variables_dict(self, code: str, variables: Dict[str, str]) -> str:
        """Update the TEST_VARIABLES dictionary in the code."""
        # Build new variables dict content
        var_lines = []
        for name, value in variables.items():
            # Escape value for Python string
            escaped_value = value.replace('\\', '\\\\').replace('"', '\\"')
            var_lines.append(f'    "{name}": "{escaped_value}",')
        
        new_dict_content = '\n'.join(var_lines)
        
        # Find and replace the TEST_VARIABLES dict
        pattern = r'TEST_VARIABLES\s*=\s*\{[^}]*\}'
        replacement = f'TEST_VARIABLES = {{\n{new_dict_content}\n}}'
        
        modified = re.sub(pattern, replacement, code, flags=re.DOTALL)
        
        return modified


class PostProcessor:
    """
    High-level interface for post-processing recorded tests.
    """
    
    def __init__(self, code: str):
        """
        Initialize post-processor.
        
        Args:
            code: The recorded test code
        """
        self.code = code
        self.analyzer = TestAnalyzer(code)
        self.modifier = TestModifier(code)
        self._inputs: Optional[List[DetectedInput]] = None
    
    def get_inputs(self) -> List[DetectedInput]:
        """Get all detected inputs."""
        if self._inputs is None:
            self._inputs = self.analyzer.analyze()
        return self._inputs
    
    def get_suggested_name(self, input_item: DetectedInput) -> str:
        """Get suggested variable name for an input."""
        return self.analyzer.get_suggested_variable_name(input_item)
    
    def set_variable(self, input_item: DetectedInput, variable_name: str) -> None:
        """Set an input to use a variable."""
        input_item.variable_name = variable_name
    
    def set_new_value(self, input_item: DetectedInput, new_value: str) -> None:
        """Set a new hardcoded value for an input."""
        input_item.new_value = new_value
    
    def clear_modification(self, input_item: DetectedInput) -> None:
        """Clear any modifications to an input."""
        input_item.variable_name = None
        input_item.new_value = None
    
    def apply(self) -> str:
        """
        Apply all modifications and return the new code.
        
        Returns:
            Modified test code
        """
        inputs = self.get_inputs()
        return self.modifier.apply_modifications(inputs)
    
    def get_summary(self) -> Dict:
        """Get a summary of detected inputs and modifications."""
        inputs = self.get_inputs()
        
        return {
            "total_inputs": len(inputs),
            "modified_inputs": sum(1 for i in inputs if i.is_modified),
            "variables_created": sum(1 for i in inputs if i.variable_name),
            "values_changed": sum(1 for i in inputs if i.new_value and not i.variable_name),
            "by_type": {
                t.value: sum(1 for i in inputs if i.input_type == t)
                for t in InputType
            }
        }
