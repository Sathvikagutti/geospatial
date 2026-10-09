"""Custom exceptions and their HTTP mappings."""


class AppError(Exception):
    """Base class for expected, user-facing errors."""

    status_code = 400
    message = "Invalid request."

    def __init__(self, message: str | None = None):
        if message:
            self.message = message
        super().__init__(self.message)


class UnsupportedFileTypeError(AppError):
    status_code = 415
    message = "Unsupported file type. Upload a .zip containing a Shapefile or a .kml file."


class EmptyFileError(AppError):
    status_code = 400
    message = "Uploaded file is empty."


class FileTooLargeError(AppError):
    status_code = 413
    message = "Uploaded file exceeds the size limit."

    def __init__(self, max_mb: int):
        self.message = f"Uploaded file exceeds the size limit of {max_mb} MB."
        super().__init__()


class InvalidArchiveError(AppError):
    status_code = 400
    message = "The .zip archive is not a valid Shapefile bundle. It must contain a .shp file together with its .shx (and ideally .dbf) sidecars."


class ShapefileParseError(AppError):
    status_code = 422
    message = "The shapefile could not be parsed."


class KmlParseError(AppError):
    status_code = 422
    message = "The KML file could not be parsed. It is not valid XML."


class NoGeometryError(AppError):
    status_code = 422
    message = "The file contains no geometric features."


class FileNotFoundError_(AppError):
    status_code = 404
    message = "File record not found."


class ProcessingFailedError(AppError):
    status_code = 500
    message = "File processing failed."
