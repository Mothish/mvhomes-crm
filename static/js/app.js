(function () {
  'use strict';
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';

  function toast(msg, isError) {
    var el = document.getElementById('toast');
    if (!el) return;
    el.textContent = msg;
    el.className = 'toast show' + (isError ? ' err' : '');
    clearTimeout(el._t);
    el._t = setTimeout(function () { el.className = 'toast'; }, 2600);
  }

  function postStage(url, data) {
    var body = new URLSearchParams(data);
    return fetch(url, {
      method: 'POST', credentials: 'same-origin', body: body,
      headers: {'X-CSRFToken': csrf, 'X-Requested-With': 'fetch'}
    }).then(function (r) { return r.json().then(function (j) { return {status: r.status, body: j}; }); });
  }

  function updateCounts() {
    document.querySelectorAll('.col').forEach(function (col) {
      col.querySelector('[data-count]').textContent = col.querySelectorAll('.lead-card').length;
    });
  }

  function initBoard() {
    var board = document.getElementById('board');
    if (!board) return;
    var dragged = null;
    var modal = document.getElementById('lost-modal'), lostForm = document.getElementById('lost-form');
    var pending = null;

    board.addEventListener('dragstart', function (e) {
      var card = e.target.closest('.lead-card');
      if (!card) return;
      dragged = card;
      card.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', card.dataset.id);
    });
    board.addEventListener('dragend', function () {
      if (dragged) dragged.classList.remove('dragging');
      document.querySelectorAll('.col.drag-over').forEach(function (c) { c.classList.remove('drag-over'); });
    });
    document.querySelectorAll('.col').forEach(function (col) {
      col.addEventListener('dragover', function (e) { e.preventDefault(); col.classList.add('drag-over'); });
      col.addEventListener('dragleave', function (e) { if (!col.contains(e.relatedTarget)) col.classList.remove('drag-over'); });
      col.addEventListener('drop', function (e) {
        e.preventDefault();
        col.classList.remove('drag-over');
        if (dragged) moveCard(dragged, col);
      });
    });

    function moveCard(card, col) {
      if (col.contains(card)) return;
      var stage = col.dataset.stage, from = card.parentElement;
      col.querySelector('.col-body').prepend(card);
      updateCounts();
      if (stage === 'lost') {
        pending = {card: card, from: from};
        lostForm.reset();
        modal.classList.add('show');
        return;
      }
      send(card, from, {stage: stage});
    }

    // Touch screens have no HTML5 drag-and-drop, so each card also has a stage picker.
    board.addEventListener('change', function (e) {
      var select = e.target.closest('.move-select');
      if (!select || !select.value) return;
      var card = select.closest('.lead-card'), col = board.querySelector('.col[data-stage="' + select.value + '"]');
      select.value = '';
      if (col) {
        moveCard(card, col);
        if (window.matchMedia('(max-width: 760px)').matches) col.scrollIntoView({behavior: 'smooth', inline: 'start', block: 'nearest'});
      }
    });

    function revert(card, from) { from.prepend(card); updateCounts(); }

    function send(card, from, data) {
      postStage(card.dataset.url, data).then(function (res) {
        if (res.body.ok) { toast(res.body.message); return; }
        revert(card, from);
        if (res.body.redirect) { toast(res.body.message); setTimeout(function () { location.href = res.body.redirect; }, 700); }
        else toast(res.body.message || 'Could not move the lead.', true);
      }).catch(function () { revert(card, from); toast('Network error, please retry.', true); });
    }

    lostForm.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!pending) return;
      var fd = new FormData(lostForm);
      if (!fd.get('reason')) { toast('Please choose a reason.', true); return; }
      modal.classList.remove('show');
      send(pending.card, pending.from, {stage: 'lost', reason: fd.get('reason'), note: fd.get('note') || ''});
      pending = null;
    });
    modal.querySelector('[data-cancel]').addEventListener('click', function () {
      modal.classList.remove('show');
      if (pending) { revert(pending.card, pending.from); pending = null; }
    });
  }

  function initDuplicateCheck(url) {
    var input = document.getElementById('id_phone'), hint = document.getElementById('dup-hint');
    if (!input || !hint) return;
    var timer;
    input.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var digits = input.value.replace(/\D/g, '');
        if (digits.length < 10) { hint.className = 'dup-hint'; return; }
        fetch(url + '?phone=' + encodeURIComponent(input.value), {credentials: 'same-origin'})
          .then(function (r) { return r.json(); })
          .then(function (d) {
            if (!d.exists) { hint.className = 'dup-hint'; return; }
            hint.textContent = '';
            var text = document.createTextNode('This number already exists' + (d.name ? ' as ' + d.name + ' (' + d.stage + ')' : '') + ', owned by ' + d.owner + '. Saving will record a re-enquiry instead of a duplicate. ');
            hint.appendChild(text);
            if (d.url) { var a = document.createElement('a'); a.href = d.url; a.textContent = 'Open lead →'; hint.appendChild(a); }
            hint.className = 'dup-hint show';
          });
      }, 350);
    });
  }

  function initBulk() {
    var all = document.getElementById('check-all'), bar = document.getElementById('bulkbar');
    if (!bar) return;
    var checks = document.querySelectorAll('.row-check');
    function refresh() {
      var n = document.querySelectorAll('.row-check:checked').length;
      document.getElementById('bulk-count').textContent = n;
      bar.classList.toggle('show', n > 0);
    }
    checks.forEach(function (c) { c.addEventListener('change', refresh); });
    if (all) all.addEventListener('change', function () { checks.forEach(function (c) { c.checked = all.checked; }); refresh(); });
  }

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') document.querySelectorAll('.modal.show').forEach(function (m) { m.classList.remove('show'); });
  });
  document.addEventListener('DOMContentLoaded', initBulk);

  window.CRM = {initBoard: initBoard, initDuplicateCheck: initDuplicateCheck, toast: toast};
})();
