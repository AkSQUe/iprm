/**
 * Molecular Network Background for IPRM
 *
 * Canvas 2D animated dots connected by lines when within proximity.
 * Two color modes: grey (default) and colored (purple + orange).
 * Cursor interaction (attract mode).
 */

(function () {
    'use strict';

    var STORAGE_KEY = 'iprm-molecules';
    var GREY = [180, 180, 180];
    var PURPLE = [112, 85, 164];
    var ORANGE = [232, 121, 58];
    var colorMode = 'grey';

    function getColorMode() {
        var saved = localStorage.getItem(STORAGE_KEY);
        return saved === 'colored' ? 'colored' : 'grey';
    }

    function pickNodeColor() {
        if (colorMode === 'colored') {
            return Math.random() < 0.65 ? PURPLE : ORANGE;
        }
        return GREY;
    }

    function applyColorMode(mode) {
        colorMode = mode;
        localStorage.setItem(STORAGE_KEY, mode);
        for (var i = 0; i < nodes.length; i++) {
            nodes[i].color = pickNodeColor();
        }
        updateToggleLabels();
    }

    function updateToggleLabels() {
        var buttons = document.querySelectorAll('.molecules-toggle');
        var label = colorMode === 'grey' ? 'Grey' : 'Color';
        for (var i = 0; i < buttons.length; i++) {
            var span = buttons[i].querySelector('.molecules-toggle__label');
            if (span) span.textContent = label;
            var dot = buttons[i].querySelector('.molecules-toggle__dot');
            if (dot) {
                dot.style.background = colorMode === 'grey' ? '#b4b4b4' : '#7055a4';
            }
        }
    }

    var animId = null;
    var nodes = [];
    var mouse = { x: -1000, y: -1000 };
    var lastTime = 0;
    var canvas, ctx, width, height, dpr;
    var effectiveSpeed, frameInterval;

    var config = {
        nodeCount: 60,
        nodeCountMobile: 25,
        linkDistance: 160,
        linkWidth: 2,
        speed: 0.2,
        nodeSize: 4,
        opacity: 0.15,
        nodeBlur: 0,
        cursorMode: 'attract',
        cursorRadius: 200,
        cursorForce: 0.02
    };

    function resize() {
        width = window.innerWidth;
        height = window.innerHeight;
        canvas.width = width * dpr;
        canvas.height = height * dpr;
        canvas.style.width = width + 'px';
        canvas.style.height = height + 'px';
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function createNode() {
        return {
            x: Math.random() * width,
            y: Math.random() * height,
            vx: (Math.random() - 0.5) * effectiveSpeed,
            vy: (Math.random() - 0.5) * effectiveSpeed,
            radius: config.nodeSize * (0.6 + Math.random() * 0.8),
            color: pickNodeColor(),
            pulseOffset: Math.random() * Math.PI * 2
        };
    }

    function initNodes() {
        var isMobile = window.innerWidth < 768;
        var count = isMobile ? config.nodeCountMobile : config.nodeCount;
        nodes = [];
        for (var i = 0; i < count; i++) {
            nodes.push(createNode());
        }
    }

    function updateNodes() {
        for (var i = 0; i < nodes.length; i++) {
            var n = nodes[i];

            if (config.cursorMode !== 'none') {
                var dx = mouse.x - n.x;
                var dy = mouse.y - n.y;
                var dist = Math.sqrt(dx * dx + dy * dy);
                if (dist < config.cursorRadius && dist > 1) {
                    var force = config.cursorForce * (1 - dist / config.cursorRadius);
                    var dir = config.cursorMode === 'repel' ? -1 : 1;
                    n.vx += (dx / dist) * force * dir;
                    n.vy += (dy / dist) * force * dir;
                }
            }

            n.vx *= 0.998;
            n.vy *= 0.998;

            var maxV = effectiveSpeed * 1.5;
            var v = Math.sqrt(n.vx * n.vx + n.vy * n.vy);
            if (v > maxV) {
                n.vx = (n.vx / v) * maxV;
                n.vy = (n.vy / v) * maxV;
            }
            var minV = effectiveSpeed * 0.2;
            if (v < minV && v > 0.001) {
                n.vx = (n.vx / v) * minV;
                n.vy = (n.vy / v) * minV;
            }

            n.x += n.vx;
            n.y += n.vy;

            var pad = 10;
            if (n.x < pad) { n.x = pad + Math.random() * 2; n.vx = Math.abs(n.vx) * 1.1; }
            if (n.x > width - pad) { n.x = width - pad - Math.random() * 2; n.vx = -Math.abs(n.vx) * 1.1; }
            if (n.y < pad) { n.y = pad + Math.random() * 2; n.vy = Math.abs(n.vy) * 1.1; }
            if (n.y > height - pad) { n.y = height - pad - Math.random() * 2; n.vy = -Math.abs(n.vy) * 1.1; }
        }
    }

    function draw() {
        ctx.clearRect(0, 0, width, height);

        var linkDistSq = config.linkDistance * config.linkDistance;

        for (var i = 0; i < nodes.length; i++) {
            for (var j = i + 1; j < nodes.length; j++) {
                var a = nodes[i];
                var b = nodes[j];
                var dx = a.x - b.x;
                var dy = a.y - b.y;
                var distSq = dx * dx + dy * dy;

                if (distSq < linkDistSq) {
                    var dist = Math.sqrt(distSq);
                    var alpha = (1 - dist / config.linkDistance) * config.opacity * 0.8;
                    var lc = a.color;
                    ctx.beginPath();
                    ctx.moveTo(a.x, a.y);
                    ctx.lineTo(b.x, b.y);
                    ctx.strokeStyle = 'rgba(' + lc[0] + ',' + lc[1] + ',' + lc[2] + ',' + alpha + ')';
                    ctx.lineWidth = config.linkWidth;
                    ctx.stroke();
                }
            }
        }

        for (var k = 0; k < nodes.length; k++) {
            var n = nodes[k];
            var r = n.radius * config.nodeSize / 2.5;
            var nc = n.color;

            ctx.beginPath();
            ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(' + nc[0] + ',' + nc[1] + ',' + nc[2] + ',' + config.opacity + ')';
            ctx.fill();
        }
    }

    function loop(timestamp) {
        animId = requestAnimationFrame(loop);
        var elapsed = timestamp - lastTime;
        if (elapsed < frameInterval) return;
        lastTime = timestamp - (elapsed % frameInterval);
        updateNodes();
        draw();
    }

    function init() {
        var container = document.getElementById('molecular-background');
        if (!container) return;

        colorMode = getColorMode();

        var reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
        var prefersReducedMotion = reducedMotionQuery.matches;
        var targetFps = prefersReducedMotion ? 10 : 60;
        frameInterval = 1000 / targetFps;
        effectiveSpeed = prefersReducedMotion ? 0.1 : config.speed;

        canvas = document.createElement('canvas');
        container.appendChild(canvas);
        ctx = canvas.getContext('2d');
        dpr = window.devicePixelRatio || 1;

        resize();
        initNodes();
        loop(0);

        var buttons = document.querySelectorAll('.molecules-toggle');
        for (var i = 0; i < buttons.length; i++) {
            buttons[i].addEventListener('click', function () {
                applyColorMode(colorMode === 'grey' ? 'colored' : 'grey');
            });
        }
        updateToggleLabels();

        document.addEventListener('mousemove', function (e) {
            mouse.x = e.clientX;
            mouse.y = e.clientY;
        }, { passive: true });

        document.addEventListener('mouseleave', function () {
            mouse.x = -1000;
            mouse.y = -1000;
        });

        window.addEventListener('resize', resize);

        document.addEventListener('visibilitychange', function () {
            if (document.hidden && animId) {
                cancelAnimationFrame(animId);
                animId = null;
            } else if (!document.hidden && !animId) {
                lastTime = 0;
                animId = requestAnimationFrame(loop);
            }
        });

        reducedMotionQuery.addEventListener('change', function (e) {
            prefersReducedMotion = e.matches;
            targetFps = e.matches ? 10 : 60;
            frameInterval = 1000 / targetFps;
            effectiveSpeed = e.matches ? 0.1 : config.speed;
            for (var i = 0; i < nodes.length; i++) {
                var n = nodes[i];
                var v = Math.sqrt(n.vx * n.vx + n.vy * n.vy);
                if (v > 0.001) {
                    var scale = effectiveSpeed / Math.max(v, 0.001);
                    n.vx *= scale;
                    n.vy *= scale;
                }
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
