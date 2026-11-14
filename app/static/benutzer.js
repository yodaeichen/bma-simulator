// Benutzerformular: Die Rollenvorlage füllt die Einzelrechte aus; die Liste der Objekte wird bei "alle Objekte" ausgegraut.
(function () {
  var preset = document.getElementById('preset');
  var form = document.getElementById('user-form');
  if (!preset || !form) return;
  var presets = JSON.parse(preset.getAttribute('data-presets'));
  var all = document.getElementById('all-objekte');
  var list = document.getElementById('objekt-list');

  function current() {
    var out = {};
    Object.keys(presets.admin).forEach(function (key) { out[key] = parseInt(form.elements['p_' + key].value, 10); });
    return out;
  }
  function matching() {
    var now = current();
    return Object.keys(presets).filter(function (name) {
      return Object.keys(presets[name]).every(function (key) { return presets[name][key] === now[key]; });
    })[0] || '';
  }
  function objekte() {
    if (form.elements.p_users.value === '2') all.checked = true;
    list.style.opacity = all.checked ? '0.45' : '';
  }
  preset.addEventListener('change', function () {
    var chosen = presets[preset.value];
    if (!chosen) return;
    Object.keys(chosen).forEach(function (key) { form.elements['p_' + key].value = String(chosen[key]); });
    objekte();
  });
  Array.prototype.forEach.call(form.querySelectorAll('.perm'), function (el) {
    el.addEventListener('change', function () { preset.value = matching(); objekte(); });
  });
  all.addEventListener('change', objekte);
  objekte();
})();
