// ==UserScript==
// @name         Instagram Docker Queue
// @namespace    nas-auto-download
// @version      0.3.0
// @description  Record loaded Instagram links, upload loaded images from browser, and send video links to Docker
// @match        https://www.instagram.com/*
// @match        https://instagram.com/*
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
    const imageUploadPath = '/api/instagram/browser-image';
    const storeKey = 'instagramRecordedLinks.v1';
    const urlPattern = /^https:\/\/www\.instagram\.com\/(p|reel|tv)\/[A-Za-z0-9_-]+\/?/i;
    const state = {
        links: new Map(),
        scanTimer: 0,
        saveTimer: 0,
        statusTimer: 0,
        lastHref: location.href,
    };

    const dockerEndpoint = () => {
        let host = String(GM_getValue('dockerHost', defaultHost)).trim().replace(/\/+$/, '');
        const port = String(GM_getValue('dockerPort', defaultPort)).trim();
        let path = String(GM_getValue('dockerPath', defaultPath)).trim();
        if (!/^https?:\/\//i.test(host)) host = `http://${host}`;
        if (path && !path.startsWith('/')) path = `/${path}`;
        if (port && !/:\d+$/.test(host.replace(/^https?:\/\//i, ''))) host = `${host}:${port}`;
        return `${host}${path || defaultPath}`;
    };

    const imageUploadEndpoint = () => {
        const endpoint = dockerEndpoint();
        return endpoint.replace(/\/api\/instagram\/links(?:\?.*)?$/i, imageUploadPath);
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

    const readStoredLinks = () => {
        try {
            const raw = GM_getValue(storeKey, '[]');
            const rows = Array.isArray(raw) ? raw : JSON.parse(raw || '[]');
            rows.forEach((row) => {
                const url = normalizeUrl(row && row.url);
                if (url) {
                    state.links.set(url, {
                        url,
                        label: String(row.label || '').trim(),
                        images: Array.isArray(row.images) ? row.images.filter(Boolean) : [],
                        firstSeen: row.firstSeen || new Date().toISOString(),
                        lastSeen: row.lastSeen || new Date().toISOString(),
                    });
                }
            });
        } catch (_error) {
            state.links.clear();
        }
    };

    const sortedLinks = () => Array.from(state.links.values())
        .sort((a, b) => String(a.firstSeen).localeCompare(String(b.firstSeen)));

    const scheduleSave = () => {
        clearTimeout(state.saveTimer);
        state.saveTimer = setTimeout(() => {
            GM_setValue(storeKey, JSON.stringify(sortedLinks()));
        }, 250);
    };

    const setStatus = (message, danger = false) => {
        const status = document.querySelector('#ig-docker-status');
        if (!status) return;
        status.textContent = message;
        status.classList.toggle('ig-danger', danger);
        clearTimeout(state.statusTimer);
        if (message) {
            state.statusTimer = setTimeout(() => {
                status.textContent = '';
                status.classList.remove('ig-danger');
            }, 6000);
        }
    };

    const updateCount = () => {
        const count = document.querySelector('#ig-docker-count');
        if (count) count.textContent = String(state.links.size);
    };

    const textFromAnchor = (anchor) => {
        const img = anchor.querySelector('img[alt]');
        const label = [
            anchor.getAttribute('aria-label'),
            anchor.textContent,
            img && img.getAttribute('alt'),
        ].filter(Boolean).join(' ').replace(/\s+/g, ' ').trim();
        return label.slice(0, 160);
    };

    const imageFromElement = (img) => {
        if (!img) return '';
        const srcset = img.getAttribute('srcset') || '';
        if (srcset) {
            const candidates = srcset.split(',').map((item) => {
                const parts = item.trim().split(/\s+/);
                const url = parts[0] || '';
                const width = Number(String(parts[1] || '').replace(/[^\d.]/g, '')) || 0;
                return {url, width};
            }).filter((item) => item.url);
            candidates.sort((a, b) => b.width - a.width);
            if (candidates[0]) return candidates[0].url;
        }
        return img.currentSrc || img.src || img.getAttribute('src') || '';
    };

    const isUsefulImage = (img) => {
        const url = imageFromElement(img);
        if (!/^https?:\/\//i.test(url)) return false;
        const width = Number(img.naturalWidth || img.width || 0);
        const height = Number(img.naturalHeight || img.height || 0);
        if (width && height && (width < 220 || height < 220)) return false;
        if (/\/profile_images?\/|s150x150|150x150|\/vp\//i.test(url)) return false;
        return true;
    };

    const collectImagesFrom = (root) => Array.from(root.querySelectorAll('img[src], img[srcset]'))
        .filter(isUsefulImage)
        .map(imageFromElement)
        .filter(Boolean)
        .filter((url, index, list) => list.indexOf(url) === index)
        .slice(0, 40);

    const mergeImages = (existing, incoming) => {
        const seen = new Set();
        const merged = [];
        [...(existing || []), ...(incoming || [])].forEach((url) => {
            const value = String(url || '').trim();
            if (!value || seen.has(value)) return;
            seen.add(value);
            merged.push(value);
        });
        return merged.slice(0, 80);
    };

    const remember = (url, label = '', images = []) => {
        const normalized = normalizeUrl(url);
        if (!normalized || !urlPattern.test(normalized)) return false;
        const now = new Date().toISOString();
        const existing = state.links.get(normalized);
        state.links.set(normalized, {
            url: normalized,
            label: label || (existing && existing.label) || '',
            images: mergeImages(existing && existing.images, images),
            firstSeen: (existing && existing.firstSeen) || now,
            lastSeen: now,
        });
        scheduleSave();
        return !existing;
    };

    const scanVisibleLinks = () => {
        let added = 0;
        const current = normalizeUrl(location.href);
        if (current && remember(current, document.title || '当前页面', collectImagesFrom(document))) added += 1;
        document.querySelectorAll('a[href]').forEach((anchor) => {
            if (remember(anchor.getAttribute('href') || '', textFromAnchor(anchor), collectImagesFrom(anchor))) added += 1;
        });
        updateCount();
        if (added > 0) setStatus(`已记录 ${state.links.size} 条链接`);
        return added;
    };

    const scheduleScan = () => {
        clearTimeout(state.scanTimer);
        state.scanTimer = setTimeout(scanVisibleLinks, 300);
    };

    const requestJson = (url, payload) => new Promise((resolve, reject) => {
        GM_xmlhttpRequest({
            method: 'POST',
            url,
            data: JSON.stringify(payload),
            headers: {'Content-Type': 'application/json'},
            timeout: 60000,
            onload: (response) => {
                let body = {};
                try {
                    body = JSON.parse(response.responseText || '{}');
                } catch (_error) {
                    reject(new Error(`Docker 返回内容不是 JSON：${response.responseText}`));
                    return;
                }
                if (response.status < 200 || response.status >= 300 || !body.ok) {
                    reject(new Error(`HTTP ${response.status}：${response.responseText}`));
                    return;
                }
                resolve(body);
            },
            onerror: (response) => reject(new Error(response.statusText || '请求错误，请检查 Docker 地址。')),
            ontimeout: () => reject(new Error('请求超时，请检查 Docker 是否可访问。')),
        });
    });

    const blobToBase64 = (blob) => new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result || '').split(',', 2)[1] || '');
        reader.onerror = () => reject(reader.error || new Error('图片读取失败'));
        reader.readAsDataURL(blob);
    });

    const fetchImageBlob = (url) => new Promise((resolve, reject) => {
        GM_xmlhttpRequest({
            method: 'GET',
            url,
            responseType: 'blob',
            timeout: 60000,
            onload: (response) => {
                if (response.status < 200 || response.status >= 300 || !response.response) {
                    reject(new Error(`图片下载失败 HTTP ${response.status}`));
                    return;
                }
                const headerText = String(response.responseHeaders || '');
                resolve({
                    blob: response.response,
                    contentType: response.response.type || headerText.match(/content-type:\s*([^\r\n]+)/i)?.[1] || 'image/jpeg',
                });
            },
            onerror: (response) => reject(new Error(response.statusText || '图片下载请求错误')),
            ontimeout: () => reject(new Error('图片下载超时')),
        });
    });

    const filenameFromImageUrl = (url, fallbackIndex) => {
        try {
            const parsed = new URL(url);
            const name = decodeURIComponent(parsed.pathname.split('/').filter(Boolean).pop() || '');
            return name || `browser_${fallbackIndex}.jpg`;
        } catch (_error) {
            return `browser_${fallbackIndex}.jpg`;
        }
    };

    const uploadBrowserImages = async (rows) => {
        let uploaded = 0;
        let skipped = 0;
        let failed = 0;
        const endpoint = imageUploadEndpoint();
        for (const row of rows) {
            const images = Array.isArray(row.images) ? row.images : [];
            for (let index = 0; index < images.length; index += 1) {
                const imageUrl = images[index];
                try {
                    setStatus(`正在上传图片 ${uploaded + skipped + failed + 1}...`);
                    const fetched = await fetchImageBlob(imageUrl);
                    const base64 = await blobToBase64(fetched.blob);
                    const body = await requestJson(endpoint, {
                        post_url: row.url,
                        source_url: imageUrl,
                        filename: filenameFromImageUrl(imageUrl, index + 1),
                        content_type: fetched.contentType,
                        data_base64: base64,
                    });
                    if (body.skipped) skipped += 1;
                    else uploaded += 1;
                } catch (error) {
                    console.warn('Instagram image upload failed', row.url, imageUrl, error);
                    failed += 1;
                }
            }
        }
        return {uploaded, skipped, failed};
    };

    const openPreview = () => {
        scanVisibleLinks();
        const rows = sortedLinks();
        if (rows.length === 0) {
            setStatus('没有记录到 Instagram 链接，先滚动加载内容。', true);
            return;
        }

        const overlay = document.createElement('div');
        overlay.className = 'ig-docker-overlay';
        const modal = document.createElement('div');
        modal.className = 'ig-docker-modal';
        modal.innerHTML = `
            <div class="ig-docker-modal-title">发送前预览</div>
            <div class="ig-docker-modal-subtitle">准备提交 ${rows.length} 条链接到 ${escapeHtml(dockerEndpoint())}，并上传已加载图片</div>
            <div class="ig-docker-list"></div>
            <div class="ig-docker-footer">
                <button type="button" data-action="select-all">全部选中</button>
                <button type="button" data-action="select-none">全部取消</button>
                <button type="button" class="primary" data-action="send">发送到 Docker</button>
                <button type="button" data-action="close">关闭</button>
            </div>
        `;
        const list = modal.querySelector('.ig-docker-list');
        rows.forEach((row, index) => {
            const item = document.createElement('label');
            item.className = 'ig-docker-row';
            item.innerHTML = `
                <input type="checkbox" checked value="${escapeHtml(row.url)}">
                <span class="ig-index">${index + 1}</span>
                <span class="ig-link">
                    <strong>${escapeHtml(row.label || shortUrl(row.url))}</strong>
                    <small>${escapeHtml(row.url)} · 图片 ${Array.isArray(row.images) ? row.images.length : 0} 张</small>
                </span>
            `;
            list.appendChild(item);
        });
        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        const close = () => overlay.remove();
        overlay.addEventListener('click', (event) => {
            if (event.target === overlay) close();
        });
        modal.addEventListener('click', async (event) => {
            const button = event.target.closest('button[data-action]');
            if (!button) return;
            const action = button.dataset.action;
            if (action === 'close') {
                close();
            } else if (action === 'select-all' || action === 'select-none') {
                modal.querySelectorAll('input[type="checkbox"]').forEach((box) => {
                    box.checked = action === 'select-all';
                });
            } else if (action === 'send') {
                const selectedUrls = Array.from(modal.querySelectorAll('input[type="checkbox"]:checked')).map((box) => box.value);
                const selectedRows = rows.filter((row) => selectedUrls.includes(row.url));
                if (selectedRows.length === 0) {
                    setStatus('没有选中要发送的链接。', true);
                    return;
                }
                button.disabled = true;
                button.textContent = '发送链接中...';
                try {
                    const body = await requestJson(dockerEndpoint(), {
                        urls: selectedRows.map((row) => row.url),
                        source: 'instagram-userscript',
                        page: location.href,
                        submitted_at: new Date().toISOString(),
                    });
                    button.textContent = '上传图片中...';
                    const imageResult = await uploadBrowserImages(selectedRows);
                    setStatus(`Docker 已接收：链接新增 ${body.accepted || 0}，已存在 ${body.skipped || 0}；图片上传 ${imageResult.uploaded}，已存在 ${imageResult.skipped}，失败 ${imageResult.failed}`);
                    close();
                } catch (error) {
                    button.disabled = false;
                    button.textContent = '发送到 Docker';
                    setStatus(`提交失败：${error.message || error}`, true);
                }
            }
        });
    };

    const shortUrl = (url) => {
        const match = String(url).match(/instagram\.com\/(?:p|reel|tv)\/([^/]+)/i);
        return match ? match[1] : url;
    };

    const escapeHtml = (value) => String(value || '').replace(/[&<>"']/g, (char) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[char]));

    const clearRecorded = () => {
        if (!confirm(`确定清空已记录的 ${state.links.size} 条 Instagram 链接吗？`)) return;
        state.links.clear();
        scheduleSave();
        updateCount();
        setStatus('已清空记录');
    };

    const setHost = () => {
        const host = prompt('Docker host', GM_getValue('dockerHost', defaultHost));
        if (host !== null) GM_setValue('dockerHost', host.trim() || defaultHost);
        const port = prompt('Docker port', GM_getValue('dockerPort', defaultPort));
        if (port !== null) GM_setValue('dockerPort', port.trim() || defaultPort);
        const path = prompt('Docker path', GM_getValue('dockerPath', defaultPath));
        if (path !== null) GM_setValue('dockerPath', path.trim() || defaultPath);
        setStatus(`当前地址：${dockerEndpoint()}`);
    };

    const injectPanel = () => {
        if (document.querySelector('#ig-docker-panel')) return;
        const style = document.createElement('style');
        style.textContent = `
            #ig-docker-panel {
                position: fixed;
                left: 18px;
                bottom: 18px;
                width: 260px;
                max-width: calc(100vw - 36px);
                background: #fff;
                color: #202124;
                border: 1px solid rgba(0,0,0,.12);
                border-radius: 14px;
                box-shadow: 0 10px 28px rgba(0,0,0,.18);
                z-index: 2147483647;
                font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                overflow: hidden;
            }
            #ig-docker-panel * { box-sizing: border-box; }
            .ig-panel-head {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 10px 12px;
                font-weight: 700;
                border-bottom: 1px solid #eee;
            }
            .ig-panel-body { padding: 10px 12px 12px; }
            .ig-muted { color: #70757a; font-size: 12px; margin-top: 2px; word-break: break-all; }
            .ig-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 10px; }
            .ig-actions button, .ig-docker-footer button {
                border: 0;
                border-radius: 999px;
                padding: 8px 10px;
                cursor: pointer;
                background: #f1f3f4;
                color: #202124;
                font-weight: 600;
            }
            .ig-actions button.primary, .ig-docker-footer button.primary { background: #1a73e8; color: #fff; }
            .ig-actions button.danger { background: #fce8e6; color: #c5221f; }
            #ig-docker-status { min-height: 18px; margin-top: 8px; font-size: 12px; color: #137333; word-break: break-word; }
            #ig-docker-status.ig-danger { color: #c5221f; }
            .ig-docker-overlay {
                position: fixed;
                inset: 0;
                background: rgba(0,0,0,.45);
                z-index: 2147483647;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 22px;
            }
            .ig-docker-modal {
                width: min(920px, 96vw);
                max-height: 86vh;
                background: #fff;
                border-radius: 18px;
                box-shadow: 0 18px 48px rgba(0,0,0,.28);
                display: flex;
                flex-direction: column;
                overflow: hidden;
                color: #202124;
                font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }
            .ig-docker-modal-title { padding: 18px 22px 6px; font-size: 20px; font-weight: 700; text-align: center; }
            .ig-docker-modal-subtitle { padding: 0 22px 12px; color: #5f6368; text-align: center; word-break: break-all; }
            .ig-docker-list { overflow: auto; padding: 0 18px; border-top: 1px solid #eee; border-bottom: 1px solid #eee; }
            .ig-docker-row {
                display: grid;
                grid-template-columns: 22px 42px minmax(0,1fr);
                gap: 10px;
                align-items: center;
                min-height: 58px;
                padding: 10px 6px;
                border-bottom: 1px solid #f1f3f4;
            }
            .ig-docker-row:last-child { border-bottom: 0; }
            .ig-index { color: #5f6368; }
            .ig-link { min-width: 0; }
            .ig-link strong, .ig-link small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
            .ig-link small { color: #5f6368; margin-top: 3px; }
            .ig-docker-footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; padding: 14px 18px; }
            @media (max-width: 640px) {
                #ig-docker-panel { left: 10px; bottom: 10px; width: calc(100vw - 20px); }
                .ig-docker-overlay { padding: 8px; }
                .ig-docker-row { grid-template-columns: 22px 30px minmax(0,1fr); }
            }
        `;
        document.head.appendChild(style);

        const panel = document.createElement('div');
        panel.id = 'ig-docker-panel';
        panel.innerHTML = `
            <div class="ig-panel-head">
                <span>Instagram Docker</span>
                <span><span id="ig-docker-count">0</span> 条</span>
            </div>
            <div class="ig-panel-body">
                <div class="ig-muted">滚动页面时会自动记录已加载的 post / reel 链接。</div>
                <div class="ig-muted">${escapeHtml(dockerEndpoint())}</div>
                <div class="ig-actions">
                    <button type="button" data-action="scan">扫描当前页</button>
                    <button type="button" class="primary" data-action="preview">预览发送</button>
                    <button type="button" data-action="settings">设置地址</button>
                    <button type="button" class="danger" data-action="clear">清空记录</button>
                </div>
                <div id="ig-docker-status"></div>
            </div>
        `;
        panel.addEventListener('click', (event) => {
            const button = event.target.closest('button[data-action]');
            if (!button) return;
            const action = button.dataset.action;
            if (action === 'scan') scanVisibleLinks();
            if (action === 'preview') openPreview();
            if (action === 'settings') setHost();
            if (action === 'clear') clearRecorded();
        });
        document.body.appendChild(panel);
        updateCount();
    };

    const observeDynamicLoading = () => {
        const observer = new MutationObserver(scheduleScan);
        observer.observe(document.documentElement, {childList: true, subtree: true, attributes: true, attributeFilter: ['href']});
        window.addEventListener('scroll', scheduleScan, {passive: true});
        window.addEventListener('focus', scheduleScan);
        document.addEventListener('mouseover', (event) => {
            const anchor = event.target.closest && event.target.closest('a[href]');
            if (anchor && remember(anchor.getAttribute('href') || '', textFromAnchor(anchor), collectImagesFrom(anchor))) updateCount();
        }, true);
        document.addEventListener('click', (event) => {
            const anchor = event.target.closest && event.target.closest('a[href]');
            if (anchor && remember(anchor.getAttribute('href') || '', textFromAnchor(anchor), collectImagesFrom(anchor))) updateCount();
        }, true);
        setInterval(() => {
            if (location.href !== state.lastHref) {
                state.lastHref = location.href;
                scheduleScan();
            }
        }, 1000);
    };

    GM_registerMenuCommand('Instagram Docker：预览发送', openPreview);
    GM_registerMenuCommand('Instagram Docker：扫描当前页', scanVisibleLinks);
    GM_registerMenuCommand('Instagram Docker：清空记录', clearRecorded);
    GM_registerMenuCommand('Instagram Docker：设置地址', setHost);

    readStoredLinks();
    injectPanel();
    observeDynamicLoading();
    scanVisibleLinks();
})();
