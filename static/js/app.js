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
    var dropBar = document.getElementById('drop-bar');
    var pointer = null, scrollTimer = null;

    // While a card is dragged, scroll the board sideways (and the page/column up/down) when the pointer
    // nears an edge, so any stage can be reached from any other in one drag.
    function autoScroll() {
      if (!dragged) return;
      scrollTimer = requestAnimationFrame(autoScroll);
      if (!pointer) return;
      var edge = 90, speed = 22, r = board.getBoundingClientRect();
      if (pointer.y > r.top && pointer.y < r.bottom) {
        if (pointer.x < r.left + edge) board.scrollLeft -= speed * (1 - Math.max(pointer.x - r.left, 0) / edge);
        else if (pointer.x > r.right - edge) board.scrollLeft += speed * (1 - Math.max(r.right - pointer.x, 0) / edge);
      }
      if (pointer.y < edge) window.scrollBy(0, -speed);
      else if (pointer.y > window.innerHeight - edge - (dropBar ? dropBar.offsetHeight : 0)) window.scrollBy(0, speed);
      var under = document.elementFromPoint(pointer.x, pointer.y), body = under && under.closest('.col-body');
      if (body) {
        var b = body.getBoundingClientRect();
        if (pointer.y < b.top + 40) body.scrollTop -= speed / 2;
        else if (pointer.y > b.bottom - 40) body.scrollTop += speed / 2;
      }
    }
    document.addEventListener('dragover', function (e) {
      if (dragged) pointer = {x: e.clientX, y: e.clientY};
    });

    function endDrag() {
      if (dragged) dragged.classList.remove('dragging');
      dragged = null;
      pointer = null;
      if (scrollTimer) cancelAnimationFrame(scrollTimer);
      if (dropBar) dropBar.classList.remove('show');
      document.querySelectorAll('.drag-over').forEach(function (c) { c.classList.remove('drag-over'); });
    }

    board.addEventListener('dragstart', function (e) {
      var card = e.target.closest('.lead-card');
      if (!card) return;
      dragged = card;
      card.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', card.dataset.id);
      if (dropBar) {
        var from = card.closest('.col').dataset.stage;
        dropBar.querySelectorAll('.drop-chip').forEach(function (c) { c.classList.toggle('current', c.dataset.stage === from); });
        dropBar.classList.add('show');
      }
      scrollTimer = requestAnimationFrame(autoScroll);
    });
    board.addEventListener('dragend', endDrag);
    if (dropBar) dropBar.querySelectorAll('.drop-chip').forEach(function (chip) {
      chip.addEventListener('dragover', function (e) { e.preventDefault(); chip.classList.add('drag-over'); });
      chip.addEventListener('dragleave', function () { chip.classList.remove('drag-over'); });
      chip.addEventListener('drop', function (e) {
        e.preventDefault();
        var card = dragged, col = board.querySelector('.col[data-stage="' + chip.dataset.stage + '"]');
        endDrag();
        if (card && col) moveCard(card, col);
      });
    });
    document.querySelectorAll('.col').forEach(function (col) {
      col.addEventListener('dragover', function (e) { e.preventDefault(); col.classList.add('drag-over'); });
      col.addEventListener('dragleave', function (e) { if (!col.contains(e.relatedTarget)) col.classList.remove('drag-over'); });
      col.addEventListener('drop', function (e) {
        e.preventDefault();
        col.classList.remove('drag-over');
        var card = dragged;
        endDrag();
        if (card) moveCard(card, col);
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
    var input = document.getElementById('id_phone'), code = document.getElementById('id_phone_code'),
        hint = document.getElementById('dup-hint');
    if (!input || !hint) return;
    var timer;
    function check() {
      clearTimeout(timer);
      timer = setTimeout(function () {
        var digits = input.value.replace(/\D/g, '');
        if (digits.length < 6) { hint.className = 'dup-hint'; return; }
        var q = '?phone=' + encodeURIComponent(input.value) + (code ? '&code=' + encodeURIComponent(code.value) : '');
        fetch(url + q, {credentials: 'same-origin'})
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
    }
    input.addEventListener('input', check);
    if (code) code.addEventListener('change', check);
  }

  // Searchable dropdown that also accepts free text. Clicking the field or the arrow always lists every option,
  // even when a value is already chosen; typing filters the list.
  function combobox(input, getOptions, onPick) {
    var wrap = document.createElement('div');
    wrap.className = 'combo';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    var toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'combo-toggle';
    toggle.tabIndex = -1;
    toggle.setAttribute('aria-label', 'Show options');
    toggle.innerHTML = '<svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>';
    var list = document.createElement('ul');
    list.className = 'combo-list';
    list.setAttribute('role', 'listbox');
    wrap.appendChild(toggle);
    wrap.appendChild(list);
    input.setAttribute('role', 'combobox');
    var active = -1, closeTimer = null;

    function render(filter) {
      clearTimeout(closeTimer);
      var q = (filter || '').trim().toLowerCase(), current = input.value.trim().toLowerCase();
      var items = getOptions().filter(function (v) { return !q || v.toLowerCase().indexOf(q) !== -1; });
      list.textContent = '';
      active = -1;
      if (!items.length) {
        var empty = document.createElement('li');
        empty.className = 'combo-empty';
        empty.textContent = input.value.trim() ? 'No match: "' + input.value.trim() + '" will be saved as typed' : 'No suggestions';
        list.appendChild(empty);
      }
      items.forEach(function (v, i) {
        var li = document.createElement('li');
        li.textContent = v;
        li.setAttribute('role', 'option');
        if (v.toLowerCase() === current) { li.className = 'selected'; active = i; }
        li.addEventListener('mousedown', function (e) { e.preventDefault(); pick(v); });
        list.appendChild(li);
      });
      wrap.classList.add('open');
      highlight();
    }
    function close() { wrap.classList.remove('open'); }
    function highlight() {
      var lis = list.querySelectorAll('li[role=option]');
      lis.forEach(function (li, i) { li.classList.toggle('active', i === active); });
      if (lis[active]) lis[active].scrollIntoView({block: 'nearest'});
    }
    function pick(v) {
      setValue(input, v);
      input.dispatchEvent(new Event('change', {bubbles: true}));
      close();
      if (onPick) onPick(v);
    }
    input.addEventListener('focus', function () { render(''); });
    input.addEventListener('click', function () { if (!wrap.classList.contains('open')) render(''); });
    input.addEventListener('input', function () { render(input.value); });
    input.addEventListener('blur', function () { closeTimer = setTimeout(close, 120); if (onPick) onPick(input.value); });
    toggle.addEventListener('mousedown', function (e) {
      e.preventDefault();
      if (input.disabled) return;
      if (wrap.classList.contains('open')) { close(); } else { input.focus(); render(''); }
    });
    input.addEventListener('keydown', function (e) {
      var lis = list.querySelectorAll('li[role=option]');
      if (e.key === 'ArrowDown') { e.preventDefault(); if (!wrap.classList.contains('open')) render(''); active = Math.min(active + 1, lis.length - 1); highlight(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); active = Math.max(active - 1, 0); highlight(); }
      else if (e.key === 'Enter' && wrap.classList.contains('open') && lis[active]) { e.preventDefault(); pick(lis[active].textContent); }
      else if (e.key === 'Escape') { close(); }
    });
  }

  function setValue(el, value) {
    el.value = value;
    if (el._syncClear) el._syncClear();
  }

  // Small × that empties a dropdown; selects without a blank option get one so they can be emptied.
  function addClear(el) {
    if (el._syncClear) return;
    var wrap = el.parentNode;
    if (!wrap.classList.contains('combo')) {
      wrap = document.createElement('div');
      wrap.className = 'clearable';
      el.parentNode.insertBefore(wrap, el);
      wrap.appendChild(el);
    }
    var x = document.createElement('button');
    x.type = 'button';
    x.className = 'clear-x';
    x.tabIndex = -1;
    x.setAttribute('aria-label', 'Clear');
    x.innerHTML = '&times;';
    wrap.appendChild(x);
    el._syncClear = function () { wrap.classList.toggle('filled', !!el.value && !el.disabled); };
    x.addEventListener('mousedown', function (e) {
      e.preventDefault();
      var isSelect = el.tagName === 'SELECT';
      if (isSelect && !Array.prototype.some.call(el.options, function (o) { return o.value === ''; })) {
        el.insertBefore(new Option('Select…', ''), el.firstChild);
      }
      el.value = '';
      el.dispatchEvent(new Event(isSelect ? 'change' : 'input', {bubbles: true}));
      el._syncClear();
      if (!isSelect) el.focus();
    });
    el.addEventListener('change', el._syncClear);
    el.addEventListener('input', el._syncClear);
    el._syncClear();
  }

  function initClearButtons() {
    document.querySelectorAll('.field select.input:not([multiple]), .combo > input').forEach(function (el) {
      // A dropdown with a single real option (e.g. WhatsApp language) has nothing to clear.
      if (el.tagName === 'SELECT' && Array.prototype.filter.call(el.options, function (o) { return o.value; }).length < 2) return;
      addClear(el);
    });
  }

  // Country -> city -> area: each level unlocks only once its parent is filled, and changing a parent clears
  // children that no longer belong to it. Country also sets the dial code and currency.
  function initLocation(dataId) {
    var el = document.getElementById(dataId);
    var country = document.getElementById('id_country'), city = document.getElementById('id_city'),
        area = document.getElementById('id_area'), dial = document.getElementById('id_phone_code'),
        currency = document.getElementById('id_currency');
    if (!el || !country || !city || !area) return;
    var geo = JSON.parse(el.textContent), dialTouched = false;

    function lower(list) { return list.map(function (v) { return v.toLowerCase(); }); }
    function citiesOf() { var c = geo[country.value]; return c ? Object.keys(c.cities) : []; }
    function cityKey() {
      var typed = city.value.trim().toLowerCase();
      return citiesOf().filter(function (n) { return n.toLowerCase() === typed; })[0];
    }
    function areasOf() {
      var c = geo[country.value], key = cityKey();
      return c && key ? c.cities[key] : [];
    }
    function areaStillValid() {
      var key = cityKey();
      return !area.value.trim() || !key || lower(geo[country.value].cities[key]).indexOf(area.value.trim().toLowerCase()) !== -1;
    }
    function lockState() {
      if (!country.value) setValue(city, '');
      city.disabled = !country.value;
      city.placeholder = country.value ? 'Select or type a city' : 'Select a country first';
      if (!city.value.trim()) setValue(area, '');
      area.disabled = !city.value.trim();
      area.placeholder = area.disabled ? 'Select a city first' : 'Select or type an area';
      [city, area].forEach(function (i) { if (i._syncClear) i._syncClear(); });
    }

    combobox(city, citiesOf, function () {
      if (!areaStillValid()) setValue(area, '');
      lockState();
    });
    combobox(area, areasOf);
    city.addEventListener('input', lockState);

    if (dial) dial.addEventListener('change', function (e) { if (e.isTrusted) dialTouched = true; });
    country.addEventListener('change', function () {
      if (lower(citiesOf()).indexOf(city.value.trim().toLowerCase()) === -1) {
        setValue(city, '');
        setValue(area, '');
      }
      var c = geo[country.value];
      if (c && dial && !dialTouched) {
        dial.value = c.dial;
        dial.dispatchEvent(new Event('change'));
      }
      if (c && currency) setValue(currency, c.currency);
      lockState();
    });
    lockState();
  }

  // Picking "Other (type your own)" reveals a required text box for the custom value.
  function initOtherFields() {
    ['source', 'property_type', 'project'].forEach(function (name) {
      var select = document.getElementById('id_' + name), other = document.getElementById('id_' + name + '_other');
      if (!select || !other) return;
      var box = other.closest('.field'), label = box.querySelector('label');
      if (label && !label.querySelector('.req')) label.insertAdjacentHTML('beforeend', ' <span class="req">*</span>');
      function show(focus) {
        var on = select.value === 'other';
        box.style.display = on ? '' : 'none';
        other.required = on;
        if (on && focus && !other.value) other.focus();
      }
      select.addEventListener('change', function () { show(true); });
      show(false);
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
  document.addEventListener('DOMContentLoaded', initClearButtons);

  // A field's server error disappears as soon as the user fills it in.
  function clearFieldError(e) {
    var field = e.target.closest && e.target.closest('.field.has-error');
    if (!field || !String(e.target.value || '').trim()) return;
    field.classList.remove('has-error');
    field.querySelectorAll('.error').forEach(function (el) { el.remove(); });
  }
  document.addEventListener('input', clearFieldError);
  document.addEventListener('change', clearFieldError);

  // ---------------------------------------------------------------- maps (Leaflet + OpenStreetMap)
  var DOHA = [25.29, 51.53];

  function baseMap(el) {
    var map = L.map(el, {scrollWheelZoom: false});
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      // The site's Referrer-Policy is same-origin; OSM tile servers require a referrer.
      referrerPolicy: 'strict-origin-when-cross-origin',
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    return map;
  }

  // Map labels are built as text nodes so names typed into the CRM are never interpreted as HTML.
  function textEl(tag, text, cls) {
    var el = document.createElement(tag);
    el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }

  function pinPopup(pin) {
    var box = textEl('div', '', 'map-pop');
    var title = textEl(pin.url ? 'a' : 'strong', pin.title, 'map-pop-title');
    if (pin.url) title.href = pin.url;
    box.appendChild(title);
    if (pin.tag) box.appendChild(textEl('span', pin.tag, 'badge b-gray'));
    (pin.lines || []).forEach(function (line) { if (line) box.appendChild(textEl('div', line)); });
    return box;
  }

  function pinsMap(elId, dataId) {
    var el = document.getElementById(elId), src = document.getElementById(dataId);
    if (!el || !src || !window.L) return null;
    var data = JSON.parse(src.textContent), map = baseMap(el), points = [];
    (data.pins || []).forEach(function (p) {
      L.circleMarker([p.lat, p.lng], {radius: 9, color: '#fff', weight: 2, fillColor: p.color || '#1f3a68', fillOpacity: 1})
        .bindPopup(pinPopup(p)).bindTooltip(textEl('span', p.title)).addTo(map);
      points.push([p.lat, p.lng]);
    });
    if (data.center) {
      L.circle(data.center, {radius: 2000, color: '#c99a3b', weight: 1, fillOpacity: 0.12}).addTo(map);
      L.marker(data.center).bindTooltip(textEl('span', data.centerLabel || 'Client')).addTo(map);
      points.push(data.center);
    }
    var demand = L.layerGroup((data.demand || []).map(function (d) {
      return L.circle([d.lat, d.lng], {radius: 700 + d.count * 400, color: '#ef4444', weight: 1, fillColor: '#ef4444', fillOpacity: 0.18})
        .bindTooltip(textEl('span', d.label + ': ' + d.count + ' open lead' + (d.count === 1 ? '' : 's')));
    }));
    if (points.length > 1) map.fitBounds(points, {padding: [30, 30], maxZoom: 14});
    else map.setView(points[0] || DOHA, points.length ? 14 : 10);
    return {map: map, demand: demand};
  }

  function initProjectsMap(elId, dataId, toggleId) {
    var result = pinsMap(elId, dataId), toggle = document.getElementById(toggleId);
    if (!result || !toggle) return;
    function sync() { if (toggle.checked) result.demand.addTo(result.map); else result.demand.remove(); }
    toggle.addEventListener('change', sync);
    sync();
  }

  function coordsFromLink(text) {
    var patterns = [/@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)/, /!3d(-?\d{1,2}\.\d+)!4d(-?\d{1,3}\.\d+)/,
                    /[?&](?:q|query|ll|destination)=(-?\d{1,2}\.\d+),\s*(-?\d{1,3}\.\d+)/];
    for (var i = 0; i < patterns.length; i++) {
      var m = patterns[i].exec(text || '');
      if (m) return [parseFloat(m[1]), parseFloat(m[2])];
    }
    return null;
  }

  // Project form: click the map, drag the pin, type coordinates or paste a Google Maps link.
  function initLocationPicker(elId) {
    var el = document.getElementById(elId), lat = document.getElementById('id_latitude'),
        lng = document.getElementById('id_longitude'), link = document.getElementById('id_maps_link');
    if (!el || !lat || !lng || !window.L) return;
    var map = baseMap(el), marker = null;
    function write(a, b) { lat.value = a.toFixed(6); lng.value = b.toFixed(6); }
    function place(a, b, pan) {
      if (marker) marker.setLatLng([a, b]);
      else {
        marker = L.marker([a, b], {draggable: true}).addTo(map);
        marker.on('dragend', function () { var p = marker.getLatLng(); write(p.lat, p.lng); });
      }
      if (pan) map.setView([a, b], Math.max(map.getZoom() || 0, 15));
    }
    function fromInputs() {
      var a = parseFloat(lat.value), b = parseFloat(lng.value);
      if (!isNaN(a) && !isNaN(b) && Math.abs(a) <= 90 && Math.abs(b) <= 180) { place(a, b, true); return true; }
      return false;
    }
    if (!fromInputs()) map.setView(DOHA, 10);
    map.on('click', function (e) { write(e.latlng.lat, e.latlng.lng); place(e.latlng.lat, e.latlng.lng); });
    lat.addEventListener('change', fromInputs);
    lng.addEventListener('change', fromInputs);
    if (link) link.addEventListener('input', function () {
      var c = coordsFromLink(link.value);
      if (c) { write(c[0], c[1]); place(c[0], c[1], true); }
    });
  }

  // Lead page "share another project": only that project's documents, and a reason when it isn't suggested.
  function initShareOther(formId) {
    var form = document.getElementById(formId);
    if (!form) return;
    var select = form.querySelector('select[name=project]'), reasonBox = form.querySelector('.share-reason'),
        reason = form.querySelector('[name=reason]');
    function sync() {
      var opt = select.options[select.selectedIndex], suggested = opt && opt.dataset.suggested === '1';
      form.querySelectorAll('[data-doc-project]').forEach(function (row) {
        var mine = row.dataset.docProject === select.value;
        row.hidden = !mine;
        row.querySelector('input').disabled = !mine;
      });
      var needReason = select.value && !suggested;
      reasonBox.hidden = !needReason;
      reason.required = needReason;
    }
    select.addEventListener('change', sync);
    sync();
  }

  // Sharing opens WhatsApp in a new tab; refresh this page so the new share appears in the history.
  document.addEventListener('submit', function (e) {
    if (e.target.matches && e.target.matches('form[data-share]') && e.target.checkValidity()) {
      setTimeout(function () { location.reload(); }, 1500);
    }
  });

  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-copy]');
    if (!btn || !navigator.clipboard) return;
    navigator.clipboard.writeText(btn.dataset.copy).then(function () { toast('Link copied'); });
  });

  window.CRM = {initBoard: initBoard, initDuplicateCheck: initDuplicateCheck, initLocation: initLocation,
                initOtherFields: initOtherFields, toast: toast, pinsMap: pinsMap, initProjectsMap: initProjectsMap,
                initLocationPicker: initLocationPicker, initShareOther: initShareOther};
})();
