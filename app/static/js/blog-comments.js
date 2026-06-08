/* Відповіді на коментарі блогу: кнопка "Відповісти" переносить спільну форму
   під потрібний коментар і виставляє parent_id. "Скасувати" -- повертає форму
   вниз і скидає parent_id. Без залежностей. */
(function() {
  'use strict';
  var form = document.getElementById('comment-form');
  if (!form) return;
  var parentInput = document.getElementById('comment-parent-id');
  var replyTo = document.getElementById('comment-reply-to');
  var replyName = document.getElementById('comment-reply-name');
  var cancel = document.getElementById('comment-reply-cancel');
  var section = document.getElementById('comments');
  var homeAnchor = document.createComment('comment-form-home');
  form.parentNode.insertBefore(homeAnchor, form);

  function reset() {
    parentInput.value = '';
    if (replyTo) replyTo.hidden = true;
    homeAnchor.parentNode.insertBefore(form, homeAnchor.nextSibling);
  }

  document.addEventListener('click', function(e) {
    var btn = e.target.closest('.blog-comment__reply');
    if (!btn) return;
    var id = btn.getAttribute('data-reply-to');
    var name = btn.getAttribute('data-reply-name') || '';
    parentInput.value = id;
    if (replyName) replyName.textContent = name;
    if (replyTo) replyTo.hidden = false;
    // перенести форму одразу під коментар, на який відповідаємо
    var li = document.getElementById('comment-' + id);
    if (li) li.appendChild(form);
    var nameField = document.getElementById('bc-name');
    if (nameField) nameField.focus();
  });

  if (cancel) cancel.addEventListener('click', reset);
})();
