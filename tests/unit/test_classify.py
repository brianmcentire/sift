"""Unit tests for sift.classify."""
import pytest
from sift.classify import classify_file


class TestClassifyFile:
    # -- Extension extraction -----------------------------------------------

    def test_plain_extension(self):
        ext, _ = classify_file("photo.jpg")
        assert ext == "jpg"

    def test_uppercase_extension_normalised(self):
        ext, _ = classify_file("photo.JPG")
        assert ext == "jpg"

    def test_mixed_case_extension(self):
        ext, _ = classify_file("photo.Jpeg")
        assert ext == "jpeg"

    def test_no_extension(self):
        ext, cat = classify_file("Makefile")
        assert ext == ""
        assert cat == "other"

    def test_dotfile_no_extension(self):
        # .gitignore — dot at position 0, no real extension
        ext, cat = classify_file(".gitignore")
        assert ext == ""
        assert cat == "other"

    def test_trailing_dot(self):
        ext, cat = classify_file("file.")
        assert ext == ""
        assert cat == "other"

    def test_multiple_dots_uses_last(self):
        ext, cat = classify_file("archive.tar.gz")
        assert ext == "gz"
        assert cat == "archive"

    # -- Category mapping ---------------------------------------------------

    def test_image_jpg(self):
        _, cat = classify_file("photo.jpg")
        assert cat == "image"

    def test_image_heic(self):
        _, cat = classify_file("IMG_001.HEIC")
        assert cat == "image"

    def test_video_mp4(self):
        _, cat = classify_file("clip.mp4")
        assert cat == "video"

    def test_video_mkv(self):
        _, cat = classify_file("movie.mkv")
        assert cat == "video"

    def test_audio_mp3(self):
        _, cat = classify_file("song.mp3")
        assert cat == "audio"

    def test_audio_flac(self):
        _, cat = classify_file("track.flac")
        assert cat == "audio"

    def test_document_pdf(self):
        _, cat = classify_file("report.pdf")
        assert cat == "document"

    def test_document_markdown(self):
        _, cat = classify_file("README.md")
        assert cat == "document"

    def test_document_csv(self):
        _, cat = classify_file("data.csv")
        assert cat == "document"

    def test_archive_zip(self):
        _, cat = classify_file("backup.zip")
        assert cat == "archive"

    def test_archive_tar_gz(self):
        _, cat = classify_file("project.tar.gz")
        assert cat == "archive"

    def test_code_python(self):
        _, cat = classify_file("script.py")
        assert cat == "code"

    def test_code_typescript(self):
        _, cat = classify_file("app.tsx")
        assert cat == "code"

    def test_code_shell(self):
        _, cat = classify_file("deploy.sh")
        assert cat == "code"

    def test_disk_vmdk(self):
        _, cat = classify_file("vm.vmdk")
        assert cat == "disk"

    def test_disk_iso(self):
        _, cat = classify_file("ubuntu.iso")
        assert cat == "disk"

    def test_font_ttf(self):
        _, cat = classify_file("Helvetica.ttf")
        assert cat == "font"

    def test_executable_exe(self):
        _, cat = classify_file("setup.exe")
        assert cat == "executable"

    def test_executable_dylib(self):
        _, cat = classify_file("lib.dylib")
        assert cat == "executable"

    def test_unknown_extension(self):
        _, cat = classify_file("data.xyzzy")
        assert cat == "other"
