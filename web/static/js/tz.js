/*
 * The only place in the project where UTC becomes local time.
 *
 * The server stores and emits UTC exclusively; templates render every instant
 * as <time data-utc="2026-10-14T12:30:00+00:00"></time> and this fills in the
 * text using the viewer's own timezone. Doing it here rather than on the server
 * means there is no zone for the server to get wrong, and the same page is
 * correct for a trader in Sydney and one in Chicago.
 */
(function () {
  'use strict';

  var zone;
  try {
    zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch (err) {
    zone = null;
  }

  var dateFormat = new Intl.DateTimeFormat(undefined, {
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  });

  function isToday(value, now) {
    return value.getFullYear() === now.getFullYear() &&
           value.getMonth() === now.getMonth() &&
           value.getDate() === now.getDate();
  }

  var timeOnly = new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  });

  function render(element) {
    var raw = element.getAttribute('data-utc');
    if (!raw) { return; }

    var value = new Date(raw);
    if (isNaN(value.getTime())) {
      // Never blank the cell on a parse failure - show what the server sent.
      element.textContent = raw;
      return;
    }

    var now = new Date();
    element.textContent = isToday(value, now)
      ? timeOnly.format(value) + ' today'
      : dateFormat.format(value);

    // The UTC value stays available on hover, which matters when comparing
    // against a broker platform that shows exchange time.
    element.setAttribute('title', raw + (zone ? ' (UTC) - shown in ' + zone : ' (UTC)'));
    element.setAttribute('datetime', raw);
  }

  function renderAll(root) {
    var nodes = (root || document).querySelectorAll('time[data-utc]');
    for (var i = 0; i < nodes.length; i++) {
      render(nodes[i]);
    }
  }

  function showZone() {
    var label = document.getElementById('tz-name');
    if (label && zone) { label.textContent = zone; }
  }

  document.addEventListener('DOMContentLoaded', function () {
    showZone();
    renderAll(document);
  });

  // HTMX replaces the "today" tables every five minutes and swaps the event
  // detail panel on click; both bring in unconverted timestamps.
  document.body.addEventListener('htmx:afterSwap', function (event) {
    renderAll(event.target);
  });
})();
