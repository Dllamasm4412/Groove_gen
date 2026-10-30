/* GrooveGen Experiment 1 (remote, Qualtrics): audio player and helpers.
 * Source only: build_qsf.py fills in the build ID, sound links, config and
 * styling, and copies the result into each question's JavaScript in the
 * generated survey (the survey header is not used).
 *
 * Written for the Qualtrics "Simple" layout and its supported API:
 * addOnload / addOnUnload, hideNextButton, showNextButton, clickNextButton,
 * getQuestionContainer, and Qualtrics.SurveyEngine.setJSEmbeddedData (saved
 * as embedded data "__js_<key>", declared in the survey flow). The player
 * draws itself into a <div class="gg-slot"> in the question text.
 *
 * Participants never see stimulus IDs, file names or condition labels.
 */
(function (w) {
  'use strict';
  if (w.GG) return;            // pages may share one window; every copy is identical
  var BUILD = /*BUILD*/'dev'/*END*/;
  var URLS = /*URLS*/{}/*END*/;
  var CONFIG = /*CONFIG*/{volume: null, hp: [], hpTimes: [[0, 1], [1.5, 2.5], [3, 4]], nMain: 27, nPractice: 2}/*END*/;
  var CSS = /*CSS*/''/*END*/;
  var PLAY_ICON = '<svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" ' +
    'd="M7 4.5v15a1 1 0 0 0 1.5.86l12.4-7.5a1 1 0 0 0 0-1.72L8.5 3.64A1 1 0 0 0 7 4.5z"/></svg>';
  var active = [];             // audio elements of the current page

  function iso() { return new Date().toISOString(); }
  function r3(x) { return Math.round(x * 1000) / 1000; }

  function setData(key, value) {
    var se = w.Qualtrics && w.Qualtrics.SurveyEngine;
    if (!se) return;
    if (se.setJSEmbeddedData) se.setJSEmbeddedData(key, value);
    else if (se.setEmbeddedData) se.setEmbeddedData('__js_' + key, value);
  }

  function addStyle() {
    if (!CSS || document.getElementById('gg-style')) return;
    var s = document.createElement('style');
    s.id = 'gg-style';
    s.textContent = CSS;
    (document.head || document.documentElement).appendChild(s);
  }

  function stopAll() {
    active.forEach(function (a) { try { a.pause(); } catch (e) { /* already gone */ } });
    active = [];
  }

  // The question text holds <div class="gg-slot">; wait briefly for it to render.
  function findSlot(q, cb) {
    var tries = 0;
    (function look() {
      var c = q.getQuestionContainer ? q.getQuestionContainer() : null;
      var slot = (c && c.querySelector('.gg-slot:not([data-gg])')) || document.querySelector('.gg-slot:not([data-gg])');
      if (slot) { slot.setAttribute('data-gg', '1'); cb(slot); return; }
      if (tries++ < 60) w.setTimeout(look, 100);
    })();
  }

  function buildUi(slot, opts) {
    slot.innerHTML = '<div class="gg-player">' +
      (opts.title ? '<p class="gg-title"></p>' : '') +
      '<p class="gg-msg">Loading…</p>' +
      (opts.intervals ? '<div class="gg-intervals"><span>1</span><span>2</span><span>3</span></div>' : '') +
      '<button type="button" class="gg-play" disabled>Loading…</button>' +
      (opts.meter ? '<div class="gg-meter" aria-hidden="true"><div></div></div>' : '') + '</div>';
    if (opts.title) slot.querySelector('.gg-title').textContent = opts.title;
    var btn = slot.querySelector('.gg-play');
    return {
      btn: btn, msg: slot.querySelector('.gg-msg'),
      fill: opts.meter ? slot.querySelector('.gg-meter > div') : null,
      boxes: opts.intervals ? slot.querySelectorAll('.gg-intervals span') : [],
      ready: function (label) { btn.disabled = false; btn.innerHTML = PLAY_ICON + '<span>' + (label || 'Play') + '</span>'; },
      busy: function (label) { btn.disabled = true; btn.textContent = label; }
    };
  }

  // Fetch the whole file first (no buffering pauses mid-clip). A host that
  // refuses cross-origin fetch is loaded by the audio element directly.
  function load(url) {
    var src = (w.fetch ? w.fetch(url, {credentials: 'omit'}).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.blob();
    }).then(function (b) {
      return URL.createObjectURL(new Blob([b], {type: 'audio/wav'}));
    }) : Promise.reject(new Error('no fetch'))).catch(function () { return url; });
    return src.then(function (s) {
      return new Promise(function (resolve, reject) {
        var a = new Audio();
        var done = false;
        a.preload = 'auto';
        a.addEventListener('canplaythrough', function () { if (!done) { done = true; resolve(a); } });
        a.addEventListener('error', function () { if (!done) { done = true; reject(new Error('audio decode')); } });
        a.src = s;
        a.load();
        active.push(a);
      });
    });
  }

  function meter(ui, a) {
    var raf = null;
    function step() {
      if (ui.fill) ui.fill.style.width = (a.duration > 0 ? Math.min(100, 100 * a.currentTime / a.duration) : 0) + '%';
      for (var i = 0; i < ui.boxes.length; i++) {
        var t = CONFIG.hpTimes[i];
        ui.boxes[i].className = (a.currentTime >= t[0] && a.currentTime < t[1]) ? 'on' : '';
      }
      raf = w.requestAnimationFrame(step);
    }
    return {
      start: function () { if (!raf) step(); },
      stop: function () { if (raf) w.cancelAnimationFrame(raf); raf = null; for (var i = 0; i < ui.boxes.length; i++) ui.boxes[i].className = ''; }
    };
  }

  // Plays a sound once from the start. A pause before the end (headphones
  // removed, a media key) is an interruption: it must be played again from
  // the start. onEnd fires once, after a complete play.
  function oncePlayer(ui, url, rec, onEnd, save) {
    var t0 = Date.now();
    load(url).then(function (a) {
      var playing = false, started = 0;
      var m = meter(ui, a);
      rec.load_ms = Date.now() - t0;
      rec.dur_s = r3(a.duration);
      ui.msg.textContent = 'Press Play when you are ready. The sound plays once.';
      ui.ready();
      ui.btn.addEventListener('click', function () {
        if (playing) return;
        playing = true;
        rec.plays += 1;
        rec.start = iso();
        started = w.performance.now();
        ui.busy('Playing…');
        a.currentTime = 0;
        save();
        a.play().catch(function (e) {
          playing = false;
          rec.errors.push('play: ' + e.name);
          save();
          ui.msg.textContent = 'Press Play to start.';
          ui.ready();
        });
      });
      a.addEventListener('playing', function () { ui.msg.textContent = 'Listening…'; m.start(); });
      a.addEventListener('waiting', function () { if (playing) rec.stalls += 1; });
      a.addEventListener('pause', function () {
        if (a.ended || !playing) return;
        playing = false;
        m.stop();
        rec.pauses.push(r3(a.currentTime));
        save();
        ui.msg.textContent = 'The sound was interrupted. Press Play to hear it again from the start.';
        ui.ready();
      });
      a.addEventListener('ended', function () {
        if (!playing) return;
        playing = false;
        m.stop();
        if (ui.fill) ui.fill.style.width = '100%';
        rec.end = iso();
        rec.played_s = r3((w.performance.now() - started) / 1000);
        rec.complete = true;
        save();
        onEnd();
      });
    }).catch(function (e) {
      rec.errors.push('load: ' + e.message);
      save();
      ui.msg.textContent = 'The sound could not be loaded. Please check your internet connection and reload ' +
        'the page. If this keeps happening, please contact the researcher (code A2).';
      ui.busy('Unavailable');
    });
  }

  function newRecord(extra) {
    var rec = {v: 2, build: BUILD, plays: 0, pauses: [], stalls: 0, load_ms: null, dur_s: null,
               start: null, end: null, played_s: null, complete: false, errors: []};
    for (var k in extra) rec[k] = extra[k];
    return rec;
  }

  function begin(q) {
    stopAll();
    addStyle();
    if (q.hideNextButton) q.hideNextButton();
  }

  // Listening page of a rating trial (practice or main). The record is saved
  // as embedded data __js_t_<sid>; after a complete play the page advances.
  function trial(q, sid, pos, kind) {
    begin(q);
    var n = parseInt(pos, 10) || null;
    var rec = newRecord({sid: sid, pos: n, kind: kind});
    var key = 'gg_plays_' + sid;
    try { rec.prior_plays = parseInt(w.sessionStorage.getItem(key) || '0', 10); } catch (e) { rec.prior_plays = null; }
    var save = function () {
      setData('t_' + sid, JSON.stringify(rec));
      try { w.sessionStorage.setItem(key, String((rec.prior_plays || 0) + rec.plays)); } catch (e) { /* private mode */ }
    };
    if (kind === 'main') setData('pos', String(n));
    var title = kind === 'practice' ? 'Practice clip ' + n + ' of ' + CONFIG.nPractice : 'Clip ' + n + ' of ' + CONFIG.nMain;
    findSlot(q, function (slot) {
      var ui = buildUi(slot, {meter: true, title: title});
      save();
      if (!URLS[sid]) {
        rec.errors.push('no url');
        save();
        ui.msg.textContent = 'This clip could not be found. Please contact the researcher (code A1).';
        ui.busy('Unavailable');
        return;
      }
      oncePlayer(ui, URLS[sid], rec, function () {
        ui.msg.textContent = 'Thank you. The questions follow.';
        ui.busy('Done');
        w.setTimeout(function () { q.clickNextButton(); }, 600);
      }, save);
    });
  }

  // Volume setup: play/stop the sample as often as wanted; Next appears after
  // it has started once. Also records the device (browser, screen) once.
  function volume(q) {
    begin(q);
    var plays = 0;
    setData('device', JSON.stringify({ua: w.navigator.userAgent, screen: [w.screen.width, w.screen.height],
                                      viewport: [w.innerWidth, w.innerHeight], touch: 'ontouchstart' in w}));
    findSlot(q, function (slot) {
      var ui = buildUi(slot, {});
      load(URLS[CONFIG.volume]).then(function (a) {
        ui.msg.textContent = '';
        ui.ready('Play sample');
        ui.btn.addEventListener('click', function () {
          if (a.paused) { a.currentTime = 0; a.play(); } else { a.pause(); }
        });
        a.addEventListener('playing', function () {
          plays += 1;
          setData('vol', String(plays));
          ui.btn.textContent = 'Stop';
          if (q.showNextButton) q.showNextButton();
        });
        a.addEventListener('pause', function () { ui.ready('Play sample'); });
      }).catch(function () {
        ui.msg.textContent = 'The sample could not be loaded. Please check your internet connection and reload ' +
          'the page (code A2).';
        ui.busy('Unavailable');
      });
    });
  }

  // Headphone check trial n (1-based), on a multiple-choice question (1, 2, 3).
  // The sound plays once; Next appears after it has ended.
  function hp(q, n) {
    begin(q);
    var rec = newRecord({hp: n});
    findSlot(q, function (slot) {
      var ui = buildUi(slot, {intervals: true});
      oncePlayer(ui, URLS[CONFIG.hp[n - 1]], rec, function () {
        ui.msg.textContent = 'Which sound contained the faint tone? Choose 1, 2 or 3 below.';
        ui.busy('Played');
        if (q.showNextButton) q.showNextButton();
      }, function () { /* the answer itself is the record */ });
    });
  }

  // Sliders: hide the handle until the participant touches the slider, so no
  // starting position is suggested (best effort; Qualtrics records no value
  // until the slider moves, and force response requires that).
  function slider(q) {
    addStyle();
    var c = q.getQuestionContainer ? q.getQuestionContainer() : null;
    if (!c) return;
    c.classList.add('gg-untouched');
    var touch = function () { c.classList.remove('gg-untouched'); };
    ['pointerdown', 'mousedown', 'touchstart', 'keydown'].forEach(function (ev) {
      c.addEventListener(ev, touch, true);
    });
  }

  // Break page: shown by display logic at loop position `at`; if display
  // logic did not apply, the page skips itself everywhere else.
  function breakAt(q, pos, at) {
    if (parseInt(pos, 10) === at) return;
    var c = q.getQuestionContainer ? q.getQuestionContainer() : null;
    if (c) c.style.visibility = 'hidden';
    q.clickNextButton();
  }

  w.GG = {trial: trial, volume: volume, hp: hp, slider: slider, breakAt: breakAt, stopAll: stopAll, build: BUILD};
})(window);
