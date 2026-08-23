/* posthog.js -- ініціалізація PostHog + відкладене завантаження SDK.

   Винесено у зовнішній файл (CLAUDE.md: No Inline Policy). Канонічний
   snippet PostHog -- inline-скрипт; тут той самий механізм, але читабельно
   й з конфігом із data-атрибутів.

   Дві частини, як і в analytics.js:

   1. Стаб-черга -- одразу, синхронно. window.posthog стає масивом, чиї
      методи складають виклики в чергу. Коли приїде array.js, він прочитає
      posthog._i і програє все накопичене. Саме тому виклики з
      posthog-events.js, зроблені до приходу SDK, не губляться.

   2. Вставка array.js -- ПІСЛЯ рендеру. Той самий мотив, що з gtag.js:
      не відбирати канал у LCP-зображення. Тригер -- що настане раніше:
      подія load, перша взаємодія або стеля LOADER_MAX_DELAY_MS.

   Ціна відкладення: сесії, обірвані до приходу SDK, втрачаються цілком --
   і подія, і запис. Той самий компроміс, який уже прийнято для GA.

   Увесь трафік іде на власний домен (data-ph-api-host, напр. '/ngx-e'),
   звідки nginx проксує його на eu.i.posthog.com. Для блокувальників це
   first-party-запити. */
(function () {
  'use strict';

  var LOADER_MAX_DELAY_MS = 3000;

  /* Методи, які стаб уміє чергувати. Список -- з офіційного snippet'а
     PostHog. Метод поза списком, викликаний до приходу SDK, кине
     TypeError, тож урізати його "бо ми стільки не вживаємо" не варто:
     дешевше тримати повний, ніж ловити падіння в чужому коді. */
  var METHODS = ('init capture register register_once register_for_session'
    + ' unregister unregister_for_session getFeatureFlag getFeatureFlagPayload'
    + ' isFeatureEnabled reloadFeatureFlags updateEarlyAccessFeatureEnrollment'
    + ' getEarlyAccessFeatures on onFeatureFlags onSessionId getSurveys'
    + ' getActiveMatchingSurveys renderSurvey canRenderSurvey getNextSurveyStep'
    + ' identify setPersonProperties group resetGroups'
    + ' setPersonPropertiesForFlags resetPersonPropertiesForFlags'
    + ' setGroupPropertiesForFlags resetGroupPropertiesForFlags reset'
    + ' get_distinct_id getGroups get_session_id get_session_replay_url alias'
    + ' set_config startSessionRecording stopSessionRecording'
    + ' sessionRecordingStarted captureException loadToolbar get_property'
    + ' getSessionProperty createPersonProfile opt_in_capturing'
    + ' opt_out_capturing has_opted_in_capturing has_opted_out_capturing'
    + ' clear_opt_in_out_capturing debug getPageViewId people.set'
    + ' people.set_once').split(' ');

  var cur = document.currentScript
    || document.querySelector('script[data-ph-key]');
  if (!cur) return;

  var key = cur.getAttribute('data-ph-key');
  if (!key) return;

  var apiHost = cur.getAttribute('data-ph-api-host') || '/ngx-e';
  /* posthog-js очікує абсолютний origin: відносний шлях він підставить у
     запити як є, але плеєр записів і тулбар будують посилання від api_host
     і на відносному шляху ламаються. */
  if (apiHost.charAt(0) === '/') {
    apiHost = window.location.origin + apiHost;
  }

  // ---- стаб-черга ----
  function queueMethod(target, name) {
    var owner = target;
    var method = name;
    // 'people.set' -> кладемо в чергу people, а не в кореневу.
    var dot = name.indexOf('.');
    if (dot !== -1) {
      owner = target[name.slice(0, dot)];
      method = name.slice(dot + 1);
    }
    owner[method] = function () {
      owner.push([method].concat(Array.prototype.slice.call(arguments, 0)));
    };
  }

  var ph = window.posthog = window.posthog || [];
  if (!ph.__SV) {
    ph._i = [];
    ph.init = function (token, config, name) {
      var target = ph;
      if (typeof name !== 'undefined') {
        ph[name] = ph[name] || [];
        target = ph[name];
      } else {
        name = 'posthog';
      }
      target.people = target.people || [];
      target.toString = function (stub) {
        var s = 'posthog';
        if (name !== 'posthog') s += '.' + name;
        if (!stub) s += ' (stub)';
        return s;
      };
      target.people.toString = function () {
        return target.toString(1) + '.people (stub)';
      };
      METHODS.forEach(function (m) { queueMethod(target, m); });
      ph._i.push([token, config, name]);
    };
    ph.__SV = 1;
  }

  // ---- конфіг ----
  var section = cur.getAttribute('data-ph-section') || 'public';
  var recording = cur.getAttribute('data-ph-recording') === '1';
  var maskAllText = cur.getAttribute('data-ph-mask-all-text') === '1';
  var userId = cur.getAttribute('data-ph-user-id') || '';

  /* Маскування реплею. maskAllInputs ховає те, що ВВОДЯТЬ; maskTextSelector
     -- те, що вже відрендерено на сторінці. В адмінці потрібне друге:
     списки учасників з ПІБ, телефонами і медпрофілями інакше поїхали б у
     запис відео. Лишаються кліки, скрол і навігація. */
  var sessionRecording = {
    maskAllInputs: true,
    maskTextSelector: maskAllText ? '*' : '[data-ph-mask]',
  };

  var config = {
    api_host: apiHost,
    // Без ui_host тулбар і плеєр записів не працюють: SDK не знає, де
    // живе сам кабінет, бо api_host вказує на наш проксі.
    ui_host: cur.getAttribute('data-ph-ui-host') || 'https://eu.posthog.com',
    person_profiles: 'identified_only',
    capture_pageview: true,
    capture_pageleave: true,
    autocapture: true,
    enable_heatmaps: true,
    capture_performance: { web_vitals: true },
    // Проксі віддає версіоновані /static/*, тож фіче-скрипти (recorder.js)
    // тягнуться тією самою версією, що й сам array.js, а не через
    // query-рядок ?v=... -- інакше кеш може змішати версії.
    strict_script_versioning: true,
    disable_session_recording: !recording,
    session_recording: sessionRecording,
    loaded: function (instance) {
      /* register ДО першого $pageview: супервластивості пишуться в
         persistence синхронно, тож потрапляють уже в стартовий перегляд.
         iprm_section -- заміна вимиканню трекінгу в адмінці: дані
         збираються скрізь, а внутрішній трафік фільтрується в UI PostHog. */
      instance.register({ iprm_section: section });

      if (userId) {
        var props = {};
        var email = cur.getAttribute('data-ph-email');
        var role = cur.getAttribute('data-ph-role');
        var lang = cur.getAttribute('data-ph-lang');
        if (email) props.email = email;
        if (role) props.iprm_role = role;
        if (lang) props.iprm_lang = lang;
        instance.identify(userId, props);
      }
    },
  };

  window.posthog.init(key, config);

  // ---- відкладена вставка array.js ----
  var loaderSrc = apiHost + '/static/array.js';
  var events = ['pointerdown', 'keydown', 'touchstart'];
  var timer = null;
  var started = false;

  function detach() {
    window.removeEventListener('load', start);
    events.forEach(function (name) {
      window.removeEventListener(name, start, true);
    });
    if (timer) {
      window.clearTimeout(timer);
      timer = null;
    }
  }

  function start() {
    if (started) return;
    started = true;
    detach();
    var script = document.createElement('script');
    script.async = true;
    script.src = loaderSrc;
    document.head.appendChild(script);
  }

  if (document.readyState === 'complete') {
    start();
  } else {
    window.addEventListener('load', start);
    events.forEach(function (name) {
      window.addEventListener(name, start, true);
    });
    timer = window.setTimeout(start, LOADER_MAX_DELAY_MS);
  }
})();
