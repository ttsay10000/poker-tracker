(function () {
  'use strict';

  // Add row in review grid (clone template row)
  function initReviewGrid() {
    var table = document.querySelector('.review-grid table tbody');
    if (!table) return;
    var templateRow = table.querySelector('tr.row-template');
    if (!templateRow) return;

    var addBtn = document.getElementById('add-row');
    if (addBtn) {
      addBtn.addEventListener('click', function () {
        var dataRows = table.querySelectorAll('tr:not(.row-template)');
        var nextIndex = dataRows.length;
        var clone = templateRow.cloneNode(true);
        clone.classList.remove('row-template');
        clone.style.display = '';
        clone.querySelectorAll('input, select').forEach(function (el) {
          if (el.name) {
            el.name = el.name.replace(/__INDEX__/g, nextIndex);
          }
          if (el.type === 'text' || el.type === 'number') el.value = '';
        });
        table.insertBefore(clone, templateRow);
      });
    }

    table.addEventListener('click', function (e) {
      if (e.target.classList.contains('remove-row')) {
        var row = e.target.closest('tr');
        if (row && !row.classList.contains('row-template') && table.querySelectorAll('tr:not(.row-template)').length > 1) {
          row.remove();
        }
      }
    });
  }

  // Player select: "Add new player" opens new tab; refresh button fetches latest players
  function initPlayerSelects() {
    var refreshBtn = document.getElementById('refresh-players');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', function () {
        fetch('/api/players', { credentials: 'same-origin' })
          .then(function (r) { return r.ok ? r.json() : []; })
          .then(function (players) {
            var selects = document.querySelectorAll('.player-select[data-player-options]');
            selects.forEach(function (sel) {
              var current = sel.value;
              sel.innerHTML = '<option value="">— Select player —</option>';
              players.forEach(function (p) {
                var opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = p.name;
                if (p.id === current) opt.selected = true;
                sel.appendChild(opt);
              });
              var newOpt = document.createElement('option');
              newOpt.value = '__new__';
              newOpt.textContent = '\u2795 Add new player';
              sel.appendChild(newOpt);
            });
          });
      });
    }
    document.querySelectorAll('.player-select[data-player-options]').forEach(function (sel) {
      sel.addEventListener('change', function () {
        if (sel.value === '__new__') {
          window.open('/players/new', '_blank', 'noopener');
          sel.value = '';
        }
      });
    });
  }

  // Drag and drop for file upload (preview) – single or multiple files
  function initUploadDrop() {
    var zone = document.getElementById('upload-zone');
    if (!zone) return;
    var input = document.getElementById('file-input');
    var preview = document.getElementById('upload-preview');
    var zoneText = document.getElementById('upload-zone-text');
    if (!input) return;

    function showPreviews(files) {
      if (!files || !files.length) return;
      preview.innerHTML = '';
      var allowed = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'];
      for (var i = 0; i < Math.min(files.length, 6); i++) {
        var file = files[i];
        if (!file.type || !file.type.startsWith('image/')) continue;
        var reader = new FileReader();
        reader.onload = (function (f) {
          return function (e) {
            var img = document.createElement('img');
            img.src = e.target.result;
            img.alt = 'Preview';
            preview.appendChild(img);
          };
        })(file);
        reader.readAsDataURL(file);
      }
      if (zoneText && files.length) zoneText.textContent = files.length + ' file(s) chosen';
      preview.style.display = 'block';
    }

    zone.addEventListener('dragover', function (e) {
      e.preventDefault();
      zone.classList.add('dragover');
    });
    zone.addEventListener('dragleave', function () {
      zone.classList.remove('dragover');
    });
    zone.addEventListener('drop', function (e) {
      e.preventDefault();
      zone.classList.remove('dragover');
      var files = e.dataTransfer && e.dataTransfer.files;
      if (files && files.length) {
        input.files = files;
        showPreviews(Array.from(files));
      }
    });
    zone.addEventListener('click', function (e) {
      if (!e.target.closest('#upload-preview')) input.click();
    });
    input.addEventListener('change', function () {
      showPreviews(input.files ? Array.from(input.files) : []);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      initReviewGrid();
      initUploadDrop();
      initPlayerSelects();
    });
  } else {
    initReviewGrid();
    initUploadDrop();
    initPlayerSelects();
  }
})();
