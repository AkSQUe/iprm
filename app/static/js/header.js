/* header.js -- навігація: dropdown, burger, scroll-ефект */
(function() {
  /* Dropdown */
  var dd = document.querySelector('.iprm-nav__dropdown');
  if (dd) {
    var btn = dd.querySelector('.iprm-nav__dropdown-toggle');
    if (btn) {
      btn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        dd.classList.toggle('open');
      });
    }
    dd.addEventListener('click', function(e) { e.stopPropagation(); });
    document.addEventListener('click', function() { dd.classList.remove('open'); });
  }

  /* Burger menu */
  var burger = document.getElementById('burger-btn');
  var nav = document.getElementById('main-nav');
  if (burger && nav) {
    burger.addEventListener('click', function() {
      var isOpen = nav.classList.toggle('open');
      burger.classList.toggle('active', isOpen);
      burger.setAttribute('aria-expanded', isOpen);
    });
    nav.querySelectorAll('a').forEach(function(link) {
      link.addEventListener('click', function() {
        nav.classList.remove('open');
        burger.classList.remove('active');
        burger.setAttribute('aria-expanded', 'false');
      });
    });
  }

  /* Scroll effect */
  var header = document.querySelector('.iprm-header');
  if (header) {
    window.addEventListener('scroll', function() {
      header.classList.toggle('scrolled', window.scrollY > 10);
    });
  }
})();
