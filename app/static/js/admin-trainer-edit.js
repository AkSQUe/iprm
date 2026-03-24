/* Auto-slug генерація для форми тренера */
document.addEventListener('DOMContentLoaded', function() {
  var nameField = document.getElementById('full_name');
  var slugField = document.getElementById('slug');
  if (!nameField || !slugField) return;

  var slugEdited = slugField.value.trim() !== '';

  slugField.addEventListener('input', function() {
    slugEdited = true;
  });

  nameField.addEventListener('input', function() {
    if (slugEdited) return;
    var text = nameField.value.toLowerCase().trim();
    text = text.replace(/[^\w\s-]/g, '');
    text = text.replace(/[\s_]+/g, '-');
    text = text.replace(/-+/g, '-');
    slugField.value = text.substring(0, 200);
  });
});
