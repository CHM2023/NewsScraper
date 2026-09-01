/*
 * The settings form. Everything here is a browser preference: the server has no
 * user table yet, so there is nowhere else to put it. See decisions.md.
 *
 * The keys are shared with the rest of the site rather than duplicated -
 * xau.timezone is read by tz.js on every page, and xau.minWeight is the same
 * key the calendar's own dropdown writes - so the two controls cannot drift.
 */
(function () {
  'use strict';

  var ZONE_KEY = 'xau.timezone';
  var WEIGHT_KEY = 'xau.minWeight';

  // Used when Intl.supportedValuesOf is missing (Safari before 17, older
  // Firefox). Enough zones to cover where this would actually be read from.
  var FALLBACK_ZONES = [
    'UTC',
    'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles',
    'America/Sao_Paulo', 'Europe/London', 'Europe/Dublin', 'Europe/Lisbon',
    'Europe/Paris', 'Europe/Berlin', 'Europe/Zurich', 'Europe/Athens',
    'Europe/Istanbul', 'Europe/Moscow', 'Africa/Cairo', 'Africa/Johannesburg',
    'Asia/Jerusalem', 'Asia/Beirut', 'Asia/Dubai', 'Asia/Karachi',
    'Asia/Kolkata', 'Asia/Bangkok', 'Asia/Shanghai', 'Asia/Hong_Kong',
    'Asia/Singapore', 'Asia/Tokyo', 'Asia/Seoul',
    'Australia/Perth', 'Australia/Sydney', 'Pacific/Auckland'
  ];

  function read(key) {
    try { return localStorage.getItem(key); } catch (err) { return null; }
  }

  function write(key, value) {
    try {
      if (value === null) { localStorage.removeItem(key); }
      else { localStorage.setItem(key, value); }
    } catch (err) { /* private mode: the page still works, it just forgets */ }
  }

  function zoneList() {
    try {
      if (typeof Intl.supportedValuesOf === 'function') {
        return Intl.supportedValuesOf('timeZone');
      }
    } catch (err) { /* fall through */ }
    return FALLBACK_ZONES;
  }

  function detected() {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone; }
    catch (err) { return null; }
  }

  function flashSaved() {
    var note = document.getElementById('saved');
    if (!note) { return; }
    note.hidden = false;
    window.setTimeout(function () { note.hidden = true; }, 1500);
  }

  document.addEventListener('DOMContentLoaded', function () {
    var tz = document.getElementById('tz-select');
    var weight = document.getElementById('weight-select');
    var detectedLabel = document.getElementById('tz-detected');
    var here = detected();

    if (detectedLabel) { detectedLabel.textContent = here || 'unknown'; }

    if (tz) {
      var auto = document.createElement('option');
      auto.value = '';
      auto.textContent = here ? 'This browser (' + here + ')' : 'This browser';
      tz.appendChild(auto);

      var zones = zoneList();
      for (var i = 0; i < zones.length; i++) {
        var option = document.createElement('option');
        option.value = zones[i];
        option.textContent = zones[i];
        tz.appendChild(option);
      }
      tz.value = read(ZONE_KEY) || '';

      tz.addEventListener('change', function () {
        write(ZONE_KEY, tz.value || null);
        flashSaved();
        // Every timestamp on the page was formatted with the old zone, and
        // FullCalendar is built once at load, so a reload is the honest way to
        // apply this rather than re-rendering half the site.
        window.location.reload();
      });
    }

    if (weight) {
      var stored = read(WEIGHT_KEY);
      weight.value = /^[1-5]$/.test(stored || '') ? stored : '1';
      weight.addEventListener('change', function () {
        write(WEIGHT_KEY, weight.value);
        flashSaved();
      });
    }
  });
})();
