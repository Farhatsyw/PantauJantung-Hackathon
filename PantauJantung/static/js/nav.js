/**
 * PantauJantung — Navbar hamburger toggle
 * Satu file, dipakai di semua halaman.
 *
 * Teknik: max-height transition (bukan display toggle).
 * Menu selalu display:flex di DOM; visibilitas dikontrol
 * murni oleh max-height + padding yang dianimasikan CSS.
 */
(function () {
  'use strict';

  /* ── Patient ID: URL → sessionStorage → links ──────────────── */
  var PID_RE = /^P\d{3,}$/;

  // Jika halaman saat ini adalah daftar pasien, hapus ID aktif dari sessionStorage
  var onIndexPage = (location.pathname === '/' || location.pathname === '/index.html');
  if (onIndexPage) {
    sessionStorage.removeItem('pj_pid');
  }

  // Bersihkan ID lama saat pengguna kembali menggunakan tombol Back
  window.addEventListener('pageshow', function (event) {
    if (event.persisted && (location.pathname === '/' || location.pathname === '/index.html')) {
      sessionStorage.removeItem('pj_pid');
    }
  });

  // Coba ambil dari ?id= di URL halaman
  var urlPid = new URLSearchParams(location.search).get('id') || '';
  if (PID_RE.test(urlPid)) {
    // Valid — simpan/perbarui sessionStorage
    sessionStorage.setItem('pj_pid', urlPid);
  }

  // Baca dari sessionStorage (mungkin diisi dari halaman sebelumnya)
  // Hapus jika tidak cocok pola yang valid
  var storedPid = sessionStorage.getItem('pj_pid') || '';
  if (storedPid && !PID_RE.test(storedPid)) {
    sessionStorage.removeItem('pj_pid');
    storedPid = '';
  }

  var activePid = PID_RE.test(storedPid) ? storedPid : '';

  // Perbarui href semua link navbar ke /dashboard.html dan /chat.html
  if (activePid) {
    var suffix = '?id=' + encodeURIComponent(activePid);
    Array.prototype.forEach.call(
      document.querySelectorAll(
        '.pj-nav__link[href="/dashboard.html"], .pj-nav__link[href="/chat.html"],' +
        '.pj-mobile-menu__link[href="/dashboard.html"], .pj-mobile-menu__link[href="/chat.html"]'
      ),
      function (link) { link.href = link.getAttribute('href') + suffix; }
    );
  } else {
    // Tidak ada ID valid — arahkan Dashboard dan Asisten AI ke /?pilih=1
    Array.prototype.forEach.call(
      document.querySelectorAll(
        '.pj-nav__link[href="/dashboard.html"], .pj-nav__link[href="/chat.html"],' +
        '.pj-mobile-menu__link[href="/dashboard.html"], .pj-mobile-menu__link[href="/chat.html"]'
      ),
      function (link) { link.href = '/?pilih=1'; }
    );
  }
  /* ────────────────────────────────────────────────────────────── */

  var btn  = document.getElementById('pj-hamburger');
  var menu = document.getElementById('pj-mobile-menu');

  if (!btn || !menu) return;

  /* ── State ──────────────────────────────────────────────── */
  var isOpen = false;

  /* ── Open ───────────────────────────────────────────────── */
  function openMenu() {
    isOpen = true;
    menu.classList.add('open');
    btn.setAttribute('aria-expanded', 'true');
    btn.setAttribute('aria-label', 'Tutup menu');
    // Defer binding outside-click so the current click
    // that opened the menu doesn't immediately close it.
    setTimeout(function () {
      document.addEventListener('click', handleOutside);
      document.addEventListener('keydown', handleKey);
    }, 0);
  }

  /* ── Close ──────────────────────────────────────────────── */
  function closeMenu() {
    isOpen = false;
    menu.classList.remove('open');
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('aria-label', 'Buka menu');
    document.removeEventListener('click', handleOutside);
    document.removeEventListener('keydown', handleKey);
  }

  /* ── Outside click ──────────────────────────────────────── */
  function handleOutside(e) {
    if (!btn.contains(e.target) && !menu.contains(e.target)) {
      closeMenu();
    }
  }

  /* ── Escape key ─────────────────────────────────────────── */
  function handleKey(e) {
    if (e.key === 'Escape') {
      closeMenu();
      btn.focus();
    }
  }

  /* ── Toggle on hamburger click ──────────────────────────── */
  btn.addEventListener('click', function (e) {
    e.stopPropagation();
    if (isOpen) { closeMenu(); } else { openMenu(); }
  });

  /* ── Close when a link inside the panel is tapped ──────── */
  Array.prototype.forEach.call(
    menu.querySelectorAll('a'),
    function (link) { link.addEventListener('click', closeMenu); }
  );

  /* ── Close on resize to desktop width ───────────────────── */
  window.addEventListener('resize', function () {
    if (window.innerWidth >= 601 && isOpen) {
      closeMenu();
    }
  });
})();
