"""플레이오토 이미지 생존 가드 테스트.

2026-08-12 데상트 391건 사고: 소싱처(무신사)가 원본 이미지를 삭제하자
S3 404 에러 XML이 .jpg로 위장한 채 EMP까지 전파 → EMP 등록은 통과,
GS이숍 채널등록의 이미지 헤더 체크에서 전량 거절.
"""

from backend.domain.samba.plugins.markets.playauto import _looks_like_image


def test_jpeg_png_gif_webp_pass() -> None:
    assert _looks_like_image(b"\xff\xd8\xff\xe0" + b"\x00" * 28)  # JPEG
    assert _looks_like_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 24)  # PNG
    assert _looks_like_image(b"GIF89a" + b"\x00" * 26)  # GIF
    assert _looks_like_image(b"RIFF\x00\x00\x00\x00WEBP")  # WebP
    assert _looks_like_image(b"BM" + b"\x00" * 30)  # BMP


def test_s3_error_xml_rejected() -> None:
    # 실사고 페이로드 — 무신사 S3 NoSuchKey 응답이 .jpg로 위장했던 그 바이트
    head = b'<?xml version="1.0" encoding="UTF-8"?>\n<Error><Code>NoSuchKey</Code>'
    assert not _looks_like_image(head[:32])


def test_html_error_page_rejected() -> None:
    assert not _looks_like_image(b"<!DOCTYPE html><html><head>")
    assert not _looks_like_image(b"  \n\t<html><body>404</body>")  # 공백 선행


def test_empty_and_garbage_rejected() -> None:
    assert not _looks_like_image(b"")
    assert not _looks_like_image(b"Not Found")
    assert not _looks_like_image(b"{\"error\": \"gone\"}")
