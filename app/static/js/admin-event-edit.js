(function() {
  var titleInput = document.getElementById('title');
  var slugInput = document.getElementById('slug');
  if (!titleInput || !slugInput) return;

  var slugManuallyEdited = slugInput.value.length > 0;

  slugInput.addEventListener('input', function() {
    slugManuallyEdited = true;
  });

  titleInput.addEventListener('input', function() {
    if (slugManuallyEdited) return;
    var text = titleInput.value.toLowerCase().trim();
    text = text.replace(/[^\w\s-]/g, '');
    text = text.replace(/[\s_]+/g, '-');
    text = text.replace(/-+/g, '-');
    slugInput.value = text.substring(0, 200);
  });
})();
