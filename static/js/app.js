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
      p.layer = L.circleMarker([p.lat, p.lng], {radius: 9, color: '#fff', weight: 2, fillColor: p.color || '#1f3a68', fillOpacity: 1})
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
    if (points.length > 1) map.fitBounds(points, {padding: [40, 40], maxZoom: 14});
    else map.setView(points[0] || DOHA, points.length ? 14 : 10);
    return {map: map, demand: demand, data: data};
  }

  // OpenStreetMap place search (free). Its usage policy needs a referrer, which the site's
  // same-origin Referrer-Policy would otherwise strip, and at most ~1 request/second (we only search on demand).
  function osm(path, params) {
    var query = Object.keys(params).map(function (k) { return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]); }).join('&');
    return fetch('https://nominatim.openstreetmap.org/' + path + '?format=jsonv2&accept-language=en&' + query,
                 {referrerPolicy: 'strict-origin-when-cross-origin'})
      .then(function (r) { if (!r.ok) throw new Error('search failed'); return r.json(); });
  }

  // Search box on the projects map: our projects/areas first, then any place via OpenStreetMap.
  function addMapSearch(map, data) {
    var Search = L.Control.extend({
      onAdd: function () {
        var box = textEl('div', '', 'map-search'), input = document.createElement('input'), list = textEl('ul', '', 'loc-results');
        input.type = 'search';
        input.className = 'input';
        input.placeholder = 'Search project or area…';
        input.setAttribute('aria-label', 'Search the map');
        list.hidden = true;
        box.appendChild(input);
        box.appendChild(list);
        L.DomEvent.disableClickPropagation(box);
        L.DomEvent.disableScrollPropagation(box);
        var found = null;
        function note(text) { list.textContent = ''; list.appendChild(textEl('li', text, 'muted')); list.hidden = false; }
        function go() {
          var raw = input.value.trim(), q = raw.toLowerCase();
          list.hidden = true;
          if (!q) return;
          var hits = (data.pins || []).filter(function (p) { return (p.title + ' ' + (p.lines || []).join(' ')).toLowerCase().indexOf(q) !== -1; });
          if (hits.length) {
            if (hits.length === 1) map.setView([hits[0].lat, hits[0].lng], 15);
            else map.fitBounds(hits.map(function (h) { return [h.lat, h.lng]; }), {padding: [50, 50], maxZoom: 15});
            hits[0].layer.openPopup();
            if (hits.length > 1) note(hits.length + ' projects match "' + raw + '"');
            return;
          }
          var city = (data.demand || []).filter(function (d) { return d.label.toLowerCase() === q; })[0];
          if (city) { map.setView([city.lat, city.lng], 12); return; }
          var b = map.getBounds();
          osm('search', {q: raw, limit: 1, viewbox: [b.getWest(), b.getNorth(), b.getEast(), b.getSouth()].join(',')})
            .then(function (res) {
              if (!res.length) { note('No project or place found for "' + raw + '"'); return; }
              var a = +res[0].lat, o = +res[0].lon;
              if (found) found.remove();
              found = L.marker([a, o]).bindTooltip(textEl('span', res[0].display_name.split(',')[0]), {permanent: true}).addTo(map);
              map.setView([a, o], 14);
            })
            .catch(function () { note('Place search is unavailable right now.'); });
        }
        input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); go(); } });
        input.addEventListener('search', go);
        return box;
      }
    });
    new Search({position: 'topright'}).addTo(map);
  }

  function initProjectsMap(elId, dataId, toggleId) {
    var result = pinsMap(elId, dataId), toggle = document.getElementById(toggleId);
    if (!result) return;
    addMapSearch(result.map, result.data);
    if (!toggle) return;
    function sync() { if (toggle.checked) result.demand.addTo(result.map); else result.demand.remove(); }
    toggle.addEventListener('change', sync);
    sync();
  }

  function coordsFromLink(text) {
    var patterns = [/@(-?\d{1,2}\.\d+),(-?\d{1,3}\.\d+)/, /!3d(-?\d{1,2}\.\d+)!4d(-?\d{1,3}\.\d+)/,
                    /[?&](?:q|query|ll|destination|center)=(-?\d{1,2}\.\d+),\s*\+?(-?\d{1,3}\.\d+)/];
    var decoded = text || '';
    try { decoded = decodeURIComponent(decoded); } catch (e) { /* keep as typed */ }
    for (var i = 0; i < patterns.length; i++) {
      var m = patterns[i].exec(decoded);
      if (m) return [parseFloat(m[1]), parseFloat(m[2])];
    }
    return null;
  }

  function looksLikeLink(text) { return /^https?:\/\//i.test(text) || /goo\.gl\/|google\.[a-z.]+\/maps/i.test(text); }

  // Project form: paste any Google Maps link, search a place name, use the device location or tap the map.
  // Coordinates stay hidden; city and area are filled from the pin when they are empty.
  function initLocationPicker(elId) {
    var el = document.getElementById(elId), lat = document.getElementById('id_latitude'),
        lng = document.getElementById('id_longitude'), box = document.getElementById('loc-picker');
    if (!el || !lat || !lng || !box || !window.L) return;
    var input = document.getElementById('loc-input'), results = document.getElementById('loc-results'),
        status = document.getElementById('loc-status'), me = document.getElementById('loc-me'),
        country = document.getElementById('id_country'), city = document.getElementById('id_city'),
        area = document.getElementById('id_area');
    var map = baseMap(el), marker = null;

    function say(text, isError) {
      status.textContent = text;
      status.classList.toggle('text-red', !!isError);
    }
    function placeMarker(a, b) {
      if (marker) { marker.setLatLng([a, b]); return; }
      marker = L.marker([a, b], {draggable: true}).addTo(map);
      marker.on('dragend', function () { var p = marker.getLatLng(); setPin(p.lat, p.lng, true); });
    }
    function setPin(a, b, keepView) {
      lat.value = a.toFixed(6);
      lng.value = b.toFixed(6);
      placeMarker(a, b);
      if (!keepView) map.setView([a, b], Math.max(map.getZoom() || 0, 16));
      say('📍 Location set. Drag the pin to fine-tune.');
      fillAddress(a, b);
    }
    function fillAddress(a, b) {
      if (!city || !area || (city.value.trim() && area.value.trim())) return;
      osm('reverse', {lat: a, lon: b, zoom: 16, addressdetails: 1}).then(function (r) {
        var ad = r.address || {}, iso = (ad.country_code || '').toUpperCase(), filled = [];
        if (country && iso && country.value !== iso &&
            Array.prototype.some.call(country.options, function (o) { return o.value === iso; })) {
          country.value = iso;
          country.dispatchEvent(new Event('change', {bubbles: true}));
        }
        var cityName = ad.city || ad.town || ad.village || ad.municipality || '';
        var areaName = ad.suburb || ad.neighbourhood || ad.quarter || ad.city_district || '';
        if (cityName && !city.value.trim()) {
          setValue(city, cityName);
          city.dispatchEvent(new Event('input', {bubbles: true}));
          var combo = city.closest('.combo');
          if (combo) combo.classList.remove('open');
          filled.push('city “' + cityName + '”');
        }
        if (areaName && !area.value.trim() && !area.disabled) {
          setValue(area, areaName);
          filled.push('area “' + areaName + '”');
        }
        if (filled.length) say('📍 Location set. Filled ' + filled.join(' and ') + ' (you can edit them).');
      }).catch(function () { /* city/area simply stay as typed */ });
    }
    function showChoices(list) {
      results.textContent = '';
      list.forEach(function (r) {
        var li = textEl('li', r.display_name);
        li.tabIndex = 0;
        function pick() { results.hidden = true; setPin(+r.lat, +r.lon); }
        li.addEventListener('click', pick);
        li.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); pick(); } });
        results.appendChild(li);
      });
      results.hidden = false;
      say('Pick the right place:');
    }
    function find() {
      var text = input.value.trim();
      results.hidden = true;
      if (!text) { say('Paste a Google Maps link or type a place name first.', true); return; }
      if (looksLikeLink(text)) {
        var c = coordsFromLink(text);
        if (c) { setPin(c[0], c[1]); return; }
        say('Reading the link…');
        fetch(box.dataset.resolveUrl + '?url=' + encodeURIComponent(text), {headers: {'X-Requested-With': 'fetch'}})
          .then(function (r) { return r.json(); })
          .then(function (d) { if (d.ok) setPin(d.lat, d.lng); else say(d.error, true); })
          .catch(function () { say('Could not read the link. Search the place name instead.', true); });
        return;
      }
      say('Searching…');
      var params = {q: text, limit: 5};
      if (country && country.value) params.countrycodes = country.value.toLowerCase();
      osm('search', params).then(function (list) {
        if (!list.length) say('No place found for “' + text + '”. Try a nearby landmark, or paste a Google Maps link.', true);
        else if (list.length === 1) setPin(+list[0].lat, +list[0].lon);
        else showChoices(list);
      }).catch(function () { say('Place search is unavailable right now. Tap the map or paste a Google Maps link.', true); });
    }

    var a = parseFloat(lat.value), b = parseFloat(lng.value);
    if (!isNaN(a) && !isNaN(b)) { placeMarker(a, b); map.setView([a, b], 15); say('📍 Location set. Drag the pin, or search again to move it.'); }
    else map.setView(DOHA, 10);

    document.getElementById('loc-find').addEventListener('click', find);
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); find(); } });
    input.addEventListener('paste', function () { setTimeout(function () { if (looksLikeLink(input.value)) find(); }, 0); });
    map.on('click', function (e) { setPin(e.latlng.lat, e.latlng.lng, true); });
    if (!navigator.geolocation) me.hidden = true;
    else me.addEventListener('click', function () {
      say('Getting your location…');
      navigator.geolocation.getCurrentPosition(
        function (p) { setPin(p.coords.latitude, p.coords.longitude); },
        function () { say('Location is blocked or unavailable on this device.', true); },
        {enableHighAccuracy: true, timeout: 10000});
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
