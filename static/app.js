(function () {
  'use strict';

  // Loading overlay: show spinner + message during form submit (upload+LLM, continue to confirm, save)
  function getLoadingOverlay() {
    var existing = document.getElementById('loading-overlay');
    if (existing) return existing;
    var overlay = document.createElement('div');
    overlay.id = 'loading-overlay';
    overlay.className = 'loading-overlay';
    overlay.setAttribute('aria-live', 'polite');
    overlay.innerHTML = '<div class="loading-spinner" aria-hidden="true"></div><p class="loading-text">Please wait…</p>';
    document.body.appendChild(overlay);
    return overlay;
  }
  function showLoading(message) {
    var overlay = getLoadingOverlay();
    var textEl = overlay.querySelector('.loading-text');
    if (textEl) textEl.textContent = message || 'Please wait…';
    overlay.classList.add('visible');
  }
  function initLoadingOverlays() {
    var addGameForm = document.getElementById('add-game-form') || document.querySelector('form[action="/games/new"]');
    if (addGameForm) {
      addGameForm.addEventListener('submit', function () {
        showLoading('Uploading & analyzing…');
      });
    }
    var reviewForm = document.getElementById('review-form');
    if (reviewForm) {
      var action = (reviewForm.getAttribute('action') || '').toLowerCase();
      if (action.indexOf('/review') !== -1 && action.indexOf('/save') === -1) {
        reviewForm.addEventListener('submit', function (e) {
          showLoading('Continuing to confirm…');
        });
        // Ensure "Continue to Confirm" actually submits: handle click so validation is visible and submit is reliable
        var continueBtn = reviewForm.querySelector('button[type="submit"]');
        if (continueBtn && continueBtn.textContent.indexOf('Continue to Confirm') !== -1) {
          continueBtn.addEventListener('click', function (e) {
            e.preventDefault();
            var validationMsg = document.getElementById('review-validation-message');
            if (validationMsg) validationMsg.remove();

            // Sync server-rendered (e.g. LLM) player selections into select values right before validation
            reviewForm.querySelectorAll('.player-select[data-player-options]').forEach(function (sel) {
              var selectedOpt = sel.querySelector('option[selected]');
              if (selectedOpt && selectedOpt.value && selectedOpt.value !== '') {
                sel.value = selectedOpt.value;
              }
            });

            // Custom validation for player rows: don't rely on browser required; check each select has a value
            var playerSelects = reviewForm.querySelectorAll('.player-select[data-player-options]');
            var firstEmpty = null;
            playerSelects.forEach(function (sel) {
              if (sel.closest('tr') && sel.closest('tr').classList.contains('row-template')) return;
              var val = (sel.value || '').trim();
              if (val === '' || val === undefined) firstEmpty = firstEmpty || sel;
            });
            if (firstEmpty) {
              firstEmpty.scrollIntoView({ behavior: 'smooth', block: 'center' });
              firstEmpty.focus();
              var msg = document.createElement('p');
              msg.id = 'review-validation-message';
              msg.setAttribute('role', 'alert');
              msg.className = 'error';
              msg.style.marginTop = '1rem';
              msg.style.marginBottom = '0';
              msg.textContent = 'Please assign a player to every row (each "Player" dropdown must have a selection).';
              continueBtn.closest('div').appendChild(msg);
              return;
            }

            if (reviewForm.checkValidity()) {
              showLoading('Continuing to confirm…');
              reviewForm.submit();
            } else {
              reviewForm.reportValidity();
              var firstInvalid = reviewForm.querySelector(':invalid');
              if (firstInvalid) {
                firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
                firstInvalid.focus();
              }
              var msg = document.createElement('p');
              msg.id = 'review-validation-message';
              msg.setAttribute('role', 'alert');
              msg.className = 'error';
              msg.style.marginTop = '1rem';
              msg.style.marginBottom = '0';
              msg.textContent = 'Please fix the highlighted field(s) above (e.g. game date or net change), then try again.';
              continueBtn.closest('div').appendChild(msg);
            }
          });
        }
      }
    }
    var confirmForm = document.getElementById('confirm-form');
    if (confirmForm) {
      confirmForm.addEventListener('submit', function () {
        showLoading('Uploading game…');
      });
    }
    // "Save and add another" submits the same form with add_another=1 (one master form, one reason field)
    var saveAddAnotherBtn = document.getElementById('save-add-another-btn');
    if (saveAddAnotherBtn && confirmForm) {
      saveAddAnotherBtn.addEventListener('click', function () {
        if (!confirmForm.checkValidity()) {
          confirmForm.reportValidity();
          return;
        }
        confirmForm.action = confirmForm.action.replace(/\?.*$/, '') + '?add_another=1';
        showLoading('Uploading game…');
        confirmForm.submit();
      });
    }
  }

  // Add row in review grid (clone template row); supports single-game (edit) and multi-game (add) forms
  function initReviewGrid() {
    var table = document.querySelector('.review-grid table tbody');
    if (table) {
      var templateRow = table.querySelector('tr.row-template');
      if (templateRow) {
        var addBtn = document.getElementById('add-row');
        if (addBtn) {
          addBtn.addEventListener('click', function () {
            var dataRows = table.querySelectorAll('tr:not(.row-template)');
            var nextIndex = dataRows.length;
            var clone = templateRow.cloneNode(true);
            clone.classList.remove('row-template');
            clone.style.display = '';
            clone.querySelectorAll('input, select').forEach(function (el) {
              el.removeAttribute('disabled');
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
    }

    // Multi-game form: each section has its own "Add row" and table
    document.querySelectorAll('.add-row-game').forEach(function (addBtn) {
      var gIdx = addBtn.getAttribute('data-game-index');
      if (gIdx === null) return;
      var section = addBtn.closest('.game-review-section');
      if (!section) return;
      var tbody = section.querySelector('tbody[data-game-index="' + gIdx + '"]');
      if (!tbody) return;
      var templateRow = tbody.querySelector('tr.row-template');
      if (!templateRow) return;
      addBtn.addEventListener('click', function () {
        var dataRows = tbody.querySelectorAll('tr:not(.row-template)');
        var nextIndex = dataRows.length;
        var clone = templateRow.cloneNode(true);
        clone.classList.remove('row-template');
        clone.style.display = '';
        clone.querySelectorAll('input, select').forEach(function (el) {
          el.removeAttribute('disabled');
          if (el.name) {
            el.name = el.name.replace(/__INDEX__/g, nextIndex);
          }
          if (el.type === 'text' || el.type === 'number') el.value = '';
        });
        tbody.insertBefore(clone, templateRow);
      });
    });
    document.addEventListener('click', function (e) {
      if (!e.target.classList.contains('remove-row')) return;
      var row = e.target.closest('tr');
      if (!row || row.classList.contains('row-template')) return;
      var tbody = row.closest('tbody');
      if (!tbody || !tbody.closest('.game-editable-table')) return;
      if (tbody.querySelectorAll('tr:not(.row-template)').length <= 1) return;
      row.remove();
    });
  }

  // Player select: "Add new player" creates player from Raw Name in same row; refresh button fetches latest players
  // Also: sync server-rendered selections (e.g. from LLM) so checkValidity() recognizes them as filled
  function initPlayerSelects() {
    // Ensure server-pre-selected player options are explicitly set on load so form validation treats them as filled
    document.querySelectorAll('.player-select[data-player-options]').forEach(function (sel) {
      var selectedOpt = sel.querySelector('option[selected]');
      if (selectedOpt && selectedOpt.value && selectedOpt.value !== '') {
        sel.value = selectedOpt.value;
      }
    });

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
        if (sel.value !== '__new__') return;
        var row = sel.closest('tr');
        var rawNameInput = row ? row.querySelector('input[name*="[raw_name]"]') : null;
        var rawName = rawNameInput ? (rawNameInput.value || '').trim() : '';
        if (!rawName) {
          window.open('/players/new', '_blank', 'noopener');
          sel.value = '';
          return;
        }
        fetch('/api/players', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: rawName })
        })
          .then(function (r) {
            if (!r.ok) return r.json().then(function (j) { throw new Error(j.detail || 'Failed to create player'); });
            return r.json();
          })
          .then(function (p) {
            var newOpt = document.createElement('option');
            newOpt.value = p.id;
            newOpt.textContent = p.name;
            sel.insertBefore(newOpt, sel.querySelector('option[value="__new__"]'));
            sel.value = p.id;
          })
          .catch(function (err) {
            alert(err.message || 'Could not add player');
            sel.value = '';
          });
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
      initLoadingOverlays();
      initReviewGrid();
      initUploadDrop();
      initPlayerSelects();
    });
  } else {
    initLoadingOverlays();
    initReviewGrid();
    initUploadDrop();
    initPlayerSelects();
  }
})();
