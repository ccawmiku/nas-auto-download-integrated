# v1.7.3-dev

- Add browser-side Instagram image upload so loaded images can be saved by Docker without sharing the browser account cookie.
- Change Instagram Docker defaults to video-only downloading; images are expected from the userscript upload path.
- Store uploaded browser images under `/downloads/instagram/{post_id}/browser-images/` with SHA-based dedupe.
