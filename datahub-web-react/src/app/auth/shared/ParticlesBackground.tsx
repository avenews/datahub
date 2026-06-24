import React, { useEffect, useRef } from 'react';
import styled from 'styled-components';

const Canvas = styled.canvas`
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    display: block;
`;

const PARTICLE_COLOR = '#37BFCC';
const LINE_COLOR = '55, 191, 204';
const PARTICLE_COUNT_DENSITY = 800;
const LINK_DISTANCE = 180;
const LINK_WIDTH = 2;
const HOVER_DISTANCE = 180;
const REPULSE_DISTANCE = 140;
const REPULSE_STRENGTH = 6;
const BASE_SPEED = 0.6;
const PARTICLE_MIN_RADIUS = 1;
const PARTICLE_MAX_RADIUS = 3;

interface Particle {
    x: number;
    y: number;
    vx: number;
    vy: number;
    r: number;
}

export default function ParticlesBackground() {
    const canvasRef = useRef<HTMLCanvasElement | null>(null);
    const particlesRef = useRef<Particle[]>([]);
    const mouseRef = useRef<{ x: number; y: number } | null>(null);
    const rafRef = useRef<number | null>(null);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return undefined;
        const ctx = canvas.getContext('2d');
        if (!ctx) return undefined;

        const dpr = window.devicePixelRatio || 1;
        let lastW = 0;
        let lastH = 0;

        const resize = () => {
            const { clientWidth, clientHeight } = canvas;
            if (clientWidth === 0 || clientHeight === 0) return;

            const reseed = particlesRef.current.length === 0 || lastW === 0 || lastH === 0;
            canvas.width = clientWidth * dpr;
            canvas.height = clientHeight * dpr;
            ctx.setTransform(1, 0, 0, 1, 0, 0);
            ctx.scale(dpr, dpr);

            const area = clientWidth * clientHeight;
            const targetCount = Math.round((area / (PARTICLE_COUNT_DENSITY * 1000)) * 80);
            const count = Math.max(30, Math.min(120, targetCount));

            if (reseed) {
                particlesRef.current = Array.from({ length: count }, () => ({
                    x: Math.random() * clientWidth,
                    y: Math.random() * clientHeight,
                    vx: (Math.random() - 0.5) * BASE_SPEED * 2,
                    vy: (Math.random() - 0.5) * BASE_SPEED * 2,
                    r: PARTICLE_MIN_RADIUS + Math.random() * (PARTICLE_MAX_RADIUS - PARTICLE_MIN_RADIUS),
                }));
            } else {
                particlesRef.current.forEach((p) => {
                    p.x = Math.min(p.x, clientWidth);
                    p.y = Math.min(p.y, clientHeight);
                });
            }

            lastW = clientWidth;
            lastH = clientHeight;
        };

        const step = () => {
            const { clientWidth: w, clientHeight: h } = canvas;
            if (w === 0 || h === 0) {
                rafRef.current = window.requestAnimationFrame(step);
                return;
            }
            if (w !== lastW || h !== lastH) resize();
            ctx.clearRect(0, 0, w, h);

            const particles = particlesRef.current;
            const mouse = mouseRef.current;
            for (let i = 0; i < particles.length; i += 1) {
                const p = particles[i];

                if (mouse) {
                    const mdx = p.x - mouse.x;
                    const mdy = p.y - mouse.y;
                    const mdist = Math.sqrt(mdx * mdx + mdy * mdy);
                    if (mdist > 0 && mdist < REPULSE_DISTANCE) {
                        const force = ((REPULSE_DISTANCE - mdist) / REPULSE_DISTANCE) * REPULSE_STRENGTH;
                        p.x += (mdx / mdist) * force;
                        p.y += (mdy / mdist) * force;
                    }
                }

                p.x += p.vx;
                p.y += p.vy;
                if (p.x < 0 || p.x > w) p.vx *= -1;
                if (p.y < 0 || p.y > h) p.vy *= -1;
                p.x = Math.max(0, Math.min(w, p.x));
                p.y = Math.max(0, Math.min(h, p.y));

                ctx.beginPath();
                ctx.fillStyle = PARTICLE_COLOR;
                ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
                ctx.fill();
            }

            for (let i = 0; i < particles.length; i += 1) {
                for (let j = i + 1; j < particles.length; j += 1) {
                    const a = particles[i];
                    const b = particles[j];
                    const dx = a.x - b.x;
                    const dy = a.y - b.y;
                    const dist = Math.sqrt(dx * dx + dy * dy);
                    if (dist < LINK_DISTANCE) {
                        const opacity = (1 - dist / LINK_DISTANCE) * 0.6;
                        ctx.strokeStyle = `rgba(${LINE_COLOR}, ${opacity})`;
                        ctx.lineWidth = LINK_WIDTH;
                        ctx.beginPath();
                        ctx.moveTo(a.x, a.y);
                        ctx.lineTo(b.x, b.y);
                        ctx.stroke();
                    }
                }

                if (mouse) {
                    const p = particles[i];
                    const dx = p.x - mouse.x;
                    const dy = p.y - mouse.y;
                    const dist = Math.sqrt(dx * dx + dy * dy);
                    if (dist < HOVER_DISTANCE) {
                        const opacity = 1 - dist / HOVER_DISTANCE;
                        ctx.strokeStyle = `rgba(${LINE_COLOR}, ${opacity})`;
                        ctx.lineWidth = LINK_WIDTH;
                        ctx.beginPath();
                        ctx.moveTo(p.x, p.y);
                        ctx.lineTo(mouse.x, mouse.y);
                        ctx.stroke();
                    }
                }
            }

            rafRef.current = window.requestAnimationFrame(step);
        };

        const handleMouseMove = (e: MouseEvent) => {
            const rect = canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            if (x < 0 || y < 0 || x > rect.width || y > rect.height) {
                mouseRef.current = null;
            } else {
                mouseRef.current = { x, y };
            }
        };
        const handleMouseLeave = () => {
            mouseRef.current = null;
        };

        resize();
        rafRef.current = window.requestAnimationFrame(step);

        const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => resize()) : null;
        if (ro) ro.observe(canvas);

        window.addEventListener('resize', resize);
        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseleave', handleMouseLeave);

        return () => {
            if (rafRef.current !== null) window.cancelAnimationFrame(rafRef.current);
            if (ro) ro.disconnect();
            window.removeEventListener('resize', resize);
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseleave', handleMouseLeave);
            particlesRef.current = [];
        };
    }, []);

    return <Canvas ref={canvasRef} />;
}
