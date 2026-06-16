// ==UserScript==
// @name         Instagram Docker Queue
// @namespace    nas-auto-download
// @version      0.1.0
// @description  Send loaded Instagram post/reel links to NAS Auto Download Docker
// @match        https://www.instagram.com/*
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @grant        GM_xmlhttpRequest
// @connect      *
// @run-at       document-end
// ==/UserScript==

(function () {
    'use strict';

    const defaultHost = '192.168.1.20';
    const defaultPort = '14001';
    const defaultPath = '/api/instagram/links';
    const urlPattern = /^https:\/\/www\.instagram\.com\/(p|reel|tv)\/[A-Za-z0-9_-]+\/?/i;

    const dockerEndpoint = () => {
        let host = String(GM_getValue('dockerHost', defaultHost)).trim().replace(/\/+$/, '');
        const port = String(GM_getValue('dockerPort', defaultPort)).trim();
        let path = String(GM_getValue('dockerPath', defaultPath)).trim();
        if (!/^https?:\/\//i.test(host)) host = `http://${host}`;
        if (path && !path.startsWith('/')) path = `/${path}`;
        if (port && !/:\d+$/.test(host.replace(/^https?:\/\//i, ''))) host = `${host}:${port}`;
        return `${host}${path || defaultPath}`;
    };

    const normalizeUrl = (value) => {
        try {
            const url = new URL(value, location.href);
            if (url.hostname !== 'www.instagram.com' && url.hostname !== 'instagram.com') return '';
            url.hostname = 'www.instagram.com';
            url.search = '';
            url.hash = '';
            const match = url.href.match(/https:\/\/www\.instagram\.com\/(p|reel|tv)\/[A-Za-z0-9_-]+\/?/i);
            return match ? match[0].replace(/\/?$/, '/') : '';
        } catch (_error) {
            return '';
        }
    };

    const collectLinks = () => {
        const urls = new Set();
        const current = normalizeUrl(location.href);
        if (current) urls.add(current);
        document.querySelectorAll('a[href]').forEach((anchor) => {
            const url = normalizeUrl(anchor.getAttribute('href') || '');
            if (url && urlPattern.test(url)) urls.add(url);
        });
        return Array.from(urls);
    };

    const sendUrls = async () => {
        const urls = collectLinks();
        if (urls.length === 0) {
            alert('没有找到已加载的 Instagram post/reel 链接。先滚动加载更多内容再试。');
            return;
        }
        const endpoint = dockerEndpoint();
        const ok = confirm(`准备发送 ${urls.length} 条 Instagram 链接到 Docker：\n${endpoint}`);
        if (!ok) return;
        GM_xmlhttpRequest({
            method: 'POST',
            url: endpoint,
            data: JSON.stringify({
                urls,
                source: 'instagram-userscript',
                page: location.href,
                submitted_at: new Date().toISOString(),
            }),
            headers: {'Content-Type': 'application/json'},
            timeout: 30000,
            onload: (response) => {
                let body = {};
                try {
                    body = JSON.parse(response.responseText || '{}');
                } catch (_error) {
                    alert(`Docker 返回内容不是 JSON：${response.responseText}`);
                    return;
                }
                if (response.status < 200 || response.status >= 300 || !body.ok) {
                    alert(`提交失败：HTTP ${response.status}\n${response.responseText}`);
                    return;
                }
                alert(`Docker 已接收 Instagram 链接。\n新增：${body.accepted}\n已存在：${body.skipped}`);
            },
            onerror: (response) => alert(response.statusText || '请求错误，请检查 Docker 地址。'),
            ontimeout: () => alert('请求超时，请检查 Docker 是否可访问。'),
        });
    };

    const setHost = () => {
        const value = prompt('Docker host', GM_getValue('dockerHost', defaultHost));
        if (value !== null) GM_setValue('dockerHost', value.trim() || defaultHost);
    };

    GM_registerMenuCommand('发送已加载 Instagram 链接到 Docker', sendUrls);
    GM_registerMenuCommand('设置 Docker Host', setHost);
})();
