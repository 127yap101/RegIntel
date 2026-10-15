"""Shared authenticated-source conditional and single-range response policy."""

from fastapi import HTTPException, Request, Response

from regintel.evidence.ranges import (
    InvalidSourceHeader,
    UnsatisfiableRange,
    bounded_header,
    if_none_match,
    if_range_matches,
    select_range,
)


def source_response(
    request: Request, data: bytes, sha256: str, *, corpus_id: str | None = None
) -> Response:
    """Call only after current auth, publication membership and source-hash checks."""

    def header(name: str) -> str | None:
        values = request.headers.getlist(name)
        if len(values) > 1:
            raise InvalidSourceHeader()
        return bounded_header(values[0] if values else None)

    size = len(data)
    etag = f'"{sha256}"'
    headers = {"ETag": etag, "Accept-Ranges": "bytes", "Cache-Control": "no-store"}
    if corpus_id is not None:
        headers["X-Corpus-Version-ID"] = corpus_id
    try:
        if if_none_match(header("if-none-match"), etag=etag):
            return Response(status_code=304, headers=headers)
        if request.method == "HEAD":
            headers["Content-Length"] = str(size)
            return Response(content=b"", media_type="application/pdf", headers=headers)
        requested_range = header("range")
        condition = header("if-range")
        selected = (
            select_range(requested_range, size=size)
            if if_range_matches(condition, etag=etag)
            else None
        )
    except InvalidSourceHeader:
        raise HTTPException(400, "Invalid source header.") from None
    except UnsatisfiableRange:
        raise HTTPException(
            416,
            "Source range is unavailable.",
            headers={**headers, "Content-Range": f"bytes */{size}"},
        ) from None
    if selected is None:
        headers["Content-Length"] = str(size)
        return Response(content=data, media_type="application/pdf", headers=headers)
    selected_bytes = data[selected.start : selected.end + 1]
    headers["Content-Range"] = f"bytes {selected.start}-{selected.end}/{size}"
    headers["Content-Length"] = str(len(selected_bytes))
    return Response(
        content=selected_bytes, status_code=206, media_type="application/pdf", headers=headers
    )
