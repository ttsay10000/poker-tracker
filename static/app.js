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

  // Drag and drop for file upload (preview)
  function initUploadDrop() {
    var zone = document.getElementById('upload-zone');
    if (!zone) return;
    var input = document.getElementById('file-input');
    var preview = document.getElementById('upload-preview');
    if (!input) return;

    function showPreview(file) {
      if (!file || !file.type.startsWith('image/')) return;
      var reader = new FileReader();
      reader.onload = function (e) {
        preview.innerHTML = '<img src="' + e.target.result + '" alt="Preview" style="max-width:100%;max-height:200px;">';
        preview.style.display = 'block';
      };
      reader.readAsDataURL(file);
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
      var file = e.dataTransfer && e.dataTransfer.files[0];
      if (file) {
        input.files = e.dataTransfer.files;
        showPreview(file);
      }
    });
    input.addEventListener('change', function () {
      showPreview(input.files[0]);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      initReviewGrid();
      initUploadDrop();
    });
  } else {
    initReviewGrid();
    initUploadDrop();
  }
})();
