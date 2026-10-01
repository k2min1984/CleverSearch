'use strict';

const documentParams = new URLSearchParams(window.location.search);
const documentId = documentParams.get('id') || '';
const documentQuery = (documentParams.get('q') || '').slice(0, 200);
const statusNode = document.getElementById('documentStatus');
const bodyNode = document.getElementById('documentBody');
const metaNode = document.getElementById('documentMeta');
const retryNode = document.getElementById('documentRetry');

function appendHighlightedText(container, value, query) {
    // Strip only the search highlight markup; all remaining source content is text.
    const text = String(value || '').replace(/<\/?mark\b[^>]*>/gi, '').replace(/&lt;\/?mark\b[^&]*&gt;/gi, '');
    const tokens = [...new Set(query.split(/\s+/).filter(token => token.length >= 2))]
        .sort((a, b) => b.length - a.length)
        .map(token => token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    container.replaceChildren();
    if (!tokens.length) {
        container.textContent = text;
        return;
    }
    const matcher = new RegExp(tokens.join('|'), 'gi');
    let offset = 0;
    for (const match of text.matchAll(matcher)) {
        container.append(document.createTextNode(text.slice(offset, match.index)));
        const mark = document.createElement('mark');
        mark.textContent = match[0];
        container.append(mark);
        offset = match.index + match[0].length;
    }
    container.append(document.createTextNode(text.slice(offset)));
}

async function loadDocument() {
    statusNode.hidden = false;
    statusNode.classList.remove('error');
    statusNode.textContent = '문서를 불러오는 중입니다…';
    bodyNode.hidden = true;
    metaNode.hidden = true;
    retryNode.hidden = true;
    try {
        if (!documentId) throw new Error('문서 번호가 없습니다. 검색 결과에서 제목을 다시 눌러 주세요.');
        const response = await fetch(`/api/v1/user/search/read/${encodeURIComponent(documentId)}`);
        if (!response.ok) {
            throw new Error(response.status === 404 ? '문서를 찾을 수 없습니다. 삭제되었는지 확인해 주세요.' : `문서를 가져오지 못했습니다. (HTTP ${response.status})`);
        }
        const data = await response.json();
        const content = data.content || data._source || data;
        const title = content.Title || content.origin_file || content.originfile || '문서';
        document.getElementById('documentTitle').textContent = title;
        document.title = `${title} | CleverSearch`;
        metaNode.replaceChildren();
        for (const [label, value] of [
            ['파일명', content.origin_file || content.originfile],
            ['카테고리', content.doc_category || content.doccategory],
            ['확장자', content.file_ext || content.fileext],
            ['색인일', String(content.indexed_at || content.indexedat || '').slice(0, 10)],
        ]) {
            const span = document.createElement('span');
            span.textContent = `${label}: ${value || '-'}`;
            metaNode.append(span);
        }
        appendHighlightedText(bodyNode, content.all_text || content.alltext || content.text || '본문 데이터 없음', documentQuery);
        statusNode.hidden = true;
        metaNode.hidden = false;
        bodyNode.hidden = false;
    } catch (error) {
        statusNode.classList.add('error');
        statusNode.textContent = error.message || '문서를 불러오지 못했습니다.';
        retryNode.hidden = !documentId;
    }
}

document.getElementById('documentSearchLink').href = documentQuery ? `/?q=${encodeURIComponent(documentQuery)}` : '/';
document.getElementById('documentClose').addEventListener('click', () => window.close());
retryNode.addEventListener('click', loadDocument);
loadDocument();
