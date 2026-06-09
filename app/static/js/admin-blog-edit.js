/* Ініціалізація редактора блогу: dropzone обкладинки + блочний редактор.
   Винесено з інлайн-скрипта (No Inline Policy). Endpoint завантаження --
   фіксований шлях (як в admin-trainer-edit.js). */
document.addEventListener('DOMContentLoaded', function() {
  var UPLOAD = '/admin/upload/blog-image';

  function slugFallback() {
    var s = document.getElementById('slug');
    var t = document.getElementById('title');
    return (s && s.value.trim()) || (t && t.value.trim()) || 'post';
  }

  if (window.initAdminDropzones) {
    window.initAdminDropzones({
      endpoint: UPLOAD,
      getSlug: slugFallback,
      slugMissingMsg: 'Спочатку вкажіть заголовок',
      allowed: ['image/png', 'image/jpeg', 'image/webp', 'image/heic', 'image/heif'],
      allowedExt: /\.(png|jpe?g|webp|heic|heif)$/i,
      allowedMsg: 'Дозволені формати: PNG, JPG, WebP, HEIC',
      maxBytes: 25 * 1024 * 1024,
      maxMsg: 'Максимальний розмір: 25 MB'
    });
  }

  if (window.initBlogEditor) {
    window.initBlogEditor({
      mount: document.getElementById('blog-editor'),
      addBar: document.getElementById('blog-editor-add'),
      field: document.getElementById('blog-content-field'),
      form: document.getElementById('blog-form'),
      uploadEndpoint: UPLOAD,
      getSlug: slugFallback
    });
  }
});
