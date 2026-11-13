// Product images in the admin: show a "no image" tile when a URL fails, and preview a pasted URL live.
"use strict";
(function () {
  function mark(img) {
    var frame = img.closest(".haat-frame");
    if (!frame) return;
    var src = img.getAttribute("src");
    frame.classList.toggle("haat-empty-img", !src);
    frame.classList.toggle("haat-broken", !!src && img.complete && img.naturalWidth === 0);
  }

  // load/error don't bubble: listen in the capture phase so lazy thumbnails are covered too.
  document.addEventListener("error", function (e) { if (e.target.tagName === "IMG") mark(e.target); }, true);
  document.addEventListener("load", function (e) { if (e.target.tagName === "IMG") mark(e.target); }, true);

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".haat-frame img").forEach(mark);  // images that settled before this ran

    var input = document.querySelector("input[data-haat-image]");
    var img = document.querySelector(".haat-preview img");
    var link = document.querySelector(".haat-original");
    if (!input || !img) return;
    var timer;
    input.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var url = input.value.trim();
        var ok = /^https?:\/\//i.test(url);
        if (ok) img.setAttribute("src", url); else img.removeAttribute("src");
        if (link) { link.href = url; link.hidden = !ok; }
        mark(img);
      }, 300);
    });
  });
})();
