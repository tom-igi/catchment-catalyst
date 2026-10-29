"""Tables filled by uploading an Excel file (`filled_by: excel` in schema.yaml).

Every such table works the same way, so there is no code for any one table:

1. Download the table as an Excel file (workbook.write_table).
2. Edit it: add, change or delete rows. The columns stay exactly as they are.
3. Upload it. The file is read and checked (workbook.read_upload), then compared
   with the table (replace.compare) for a preview of what will change.
4. Once approved, the table's rows are replaced with the file's (replace.replace).

The admin page (backend/catalyst/admin/) does these steps through a web page.
"""

from .replace import Changed, Comparison, compare, key_columns, lock, replace
from .workbook import FileRow, UploadError, read_upload, show_value, type_label, write_table

__all__ = [
    "Changed", "Comparison", "FileRow", "UploadError", "compare", "key_columns", "lock",
    "read_upload", "replace", "show_value", "type_label", "write_table",
]
