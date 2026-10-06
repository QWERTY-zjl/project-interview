/**
 * 面试报告下载工具（interview.html 和 record_detail.html 共用）
 * ================================================================
 * 把报告数据渲染成一份排版好的网页文件（.html）供用户下载：
 * 用户双击下载的文件就能在浏览器里看到一份完整的面试报告，
 * 也可以在浏览器里 Ctrl+P 直接"打印/另存为 PDF"。
 *
 * 为什么是 HTML 而不是 JSON/PDF：
 * - JSON 是给程序读的，普通用户看不懂（本项目真实反馈）；
 * - 生成 PDF 需要后端装 weasyprint 等依赖，前端纯浏览器环境做不到；
 * - HTML 是两者之间的最优解：人能直接读，浏览器原生支持，还能打印成 PDF。
 *
 * 用法：页面先引入本文件（<script src="js/report_download.js">），
 *       再调用 downloadInterviewReport(统一数据对象)。
 * 数据对象字段（均可选，缺什么区块就不渲染什么）：
 *   position        岗位名            time      面试时间（已格式化的字符串）
 *   totalScore      综合总分(0-100)   recommendation  录用建议文字
 *   scores          三维分 {professional, communication, comprehensive}
 *   detailedScores  细分能力 [{name, score(0-10), percentage}]
 *   description     总体评价文字
 *   strengths       优势 [字符串]     improvements  待改进 [字符串]
 *   recommendations AI建议 [{title, description}]（兼容纯字符串）
 *   questions       逐题明细 [{text, answer, score, comment}]
 *
 * 版权声明：仅供学习参考，禁止商用/二次分发/他用本代码申请软著
 */

/**
 * HTML 转义：把 < > & " ' 换成 HTML 实体。
 * 【为什么要转义】报告内容（题目/回答/点评）来自大模型和用户输入，
 * 里面可能有 <script> 这类字符，不转义的话拼进 HTML 会被浏览器当成
 * 标签执行（XSS 注入），至少也会导致排版错乱。
 * String(x) 先把非字符串（数字/undefined/null）统一转成字符串再替换。
 */
function escapeHtml(value) {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * 建议/优势条目统一成 {title, desc}：
 * 新报告的 recommendations 每条是 {title, description} 对象，
 * 历史报告可能是纯字符串——两种都兼容，避免再出现"把 JSON 原文显示出来"的错配
 */
function normalizeAdvice(item) {
    if (item && typeof item === 'object') {
        return { title: item.title || '', desc: item.description || item.desc || '' };
    }
    return { title: '', desc: String(item || '') };
}

/**
 * 主函数：生成 HTML 报告并触发浏览器下载
 * @param {object} data 见文件头说明
 */
function downloadInterviewReport(data) {
    data = data || {};
    const esc = escapeHtml;

    // ---------- 区块 1：头部（岗位/时间/总分/录用建议） ----------
    // 录用建议按文案配颜色：推荐录用=绿、可以考虑=黄、不建议录用=红
    const recColorMap = {
        '推荐录用': ['#16a34a', 'rgba(22,163,74,.12)'],
        '可以考虑': ['#d97706', 'rgba(217,119,6,.12)'],
        '不建议录用': ['#dc2626', 'rgba(220,38,38,.12)']
    };
    const recStyle = recColorMap[data.recommendation] || ['#475569', 'rgba(71,85,105,.1)'];
    const headHtml = `
      <div class="head">
        <div>
          <div class="position">${esc(data.position || '模拟面试')}</div>
          <div class="time">面试时间：${esc(data.time || '未记录')}</div>
        </div>
        <div class="right">
          <div class="score">${esc(data.totalScore == null ? '-' : data.totalScore)}<span> 分</span></div>
          <div class="score-label">综合评分</div>
          ${data.recommendation ? `<span class="rec-badge" style="color:${recStyle[0]};background:${recStyle[1]}">${esc(data.recommendation)}</span>` : ''}
        </div>
      </div>`;

    // ---------- 区块 2：三维评分条 ----------
    // Object.entries 把对象拆成 [键, 值] 数组；filter 去掉没分的维度
    const dimNames = { professional: '专业知识', communication: '表达能力', comprehensive: '综合素养' };
    const dimsHtml = Object.entries(dimNames)
        .filter(([key]) => data.scores && data.scores[key] !== undefined && data.scores[key] !== null)
        .map(([key, name]) => `
          <div class="row">
            <span class="row-label">${name}</span>
            <div class="track"><div class="fill" style="width:${esc(data.scores[key])}%"></div></div>
            <span class="row-value">${esc(data.scores[key])}</span>
          </div>`).join('');

    // ---------- 区块 3：细分能力（模型可能没返回，空就不显示） ----------
    const detailHtml = (data.detailedScores && data.detailedScores.length) ? `
      <h2>细分能力</h2>
      ${data.detailedScores.map(d => `
        <div class="row">
          <span class="row-label">${esc(d.name)}</span>
          <div class="track"><div class="fill" style="width:${esc(d.percentage || 0)}%"></div></div>
          <span class="row-value">${esc(d.score)}/10</span>
        </div>`).join('')}` : '';

    // ---------- 区块 4：总体评价 / 优势 / 待改进 / AI建议 ----------
    const adviceHtml = (list) => (list || []).map(normalizeAdvice).map(a =>
        `<li>${a.title ? `<b>${esc(a.title)}：</b>` : ''}${esc(a.desc)}</li>`).join('');
    const summaryHtml = `
      ${data.description ? `<h2>总体评价</h2><p class="desc">${esc(data.description)}</p>` : ''}
      <div class="cols">
        ${(data.strengths && data.strengths.length) ? `
          <div class="col"><h3 class="green">✓ 优势</h3><ul>${adviceHtml(data.strengths)}</ul></div>` : ''}
        ${(data.improvements && data.improvements.length) ? `
          <div class="col"><h3 class="amber">△ 待改进</h3><ul>${adviceHtml(data.improvements)}</ul></div>` : ''}
        ${(data.recommendations && data.recommendations.length) ? `
          <div class="col"><h3 class="blue">★ AI 建议</h3><ul>${adviceHtml(data.recommendations)}</ul></div>` : ''}
      </div>`;

    // ---------- 区块 5：逐题明细（题目+回答+得分+点评） ----------
    // (q, i) => ... 生成每一题的 HTML；q.score 是数字才显示分数
    const questionsHtml = (data.questions && data.questions.length) ? `
      <h2>问答明细</h2>
      ${data.questions.map((q, i) => `
        <div class="qa">
          <div class="q-line">
            <span class="q-index">${i + 1}</span>
            <span class="q-text">${esc(q.text)}</span>
            ${typeof q.score === 'number' ? `<span class="q-score">${q.score} 分</span>` : ''}
          </div>
          <div class="q-block"><div class="q-label">你的回答</div>
            <div class="q-content">${esc(q.answer) ? esc(q.answer) : '<i>未回答</i>'}</div></div>
          ${q.comment ? `<div class="q-comment">点评：${esc(q.comment)}</div>` : ''}
        </div>`).join('')}` : '';

    // ---------- 组装完整文档并下载 ----------
    // toLocaleString 把当前时间转成本地可读格式，作为报告生成时间
    const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>面试报告_${esc(data.position || '模拟面试')}</title>
<style>
  /* 亮色主题：屏幕看着舒服，打印（Ctrl+P 存 PDF）也不费墨 */
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #f1f5f9; color: #1e293b; padding: 32px 16px; line-height: 1.7; }
  .page { max-width: 820px; margin: 0 auto; background: #fff; border-radius: 12px;
          padding: 36px 40px; box-shadow: 0 2px 12px rgba(0,0,0,.08); }
  .head { display: flex; justify-content: space-between; align-items: flex-start;
          border-bottom: 2px solid #3b82f6; padding-bottom: 18px; margin-bottom: 24px; }
  .title-tag { font-size: 12px; color: #3b82f6; letter-spacing: 2px; margin-bottom: 6px; }
  .position { font-size: 24px; font-weight: 800; }
  .time { color: #64748b; font-size: 13px; margin-top: 6px; }
  .right { text-align: right; }
  .score { font-size: 42px; font-weight: 800; color: #3b82f6; line-height: 1; }
  .score span { font-size: 14px; color: #64748b; font-weight: 400; }
  .score-label { font-size: 12px; color: #94a3b8; margin-top: 4px; }
  .rec-badge { display: inline-block; margin-top: 8px; padding: 3px 12px;
               border-radius: 9999px; font-size: 13px; font-weight: 600; }
  h2 { font-size: 16px; margin: 26px 0 12px; padding-left: 10px;
       border-left: 4px solid #3b82f6; }
  h3 { font-size: 14px; margin-bottom: 8px; }
  .row { display: flex; align-items: center; margin-bottom: 10px; }
  .row-label { width: 90px; font-size: 13px; color: #475569; flex-shrink: 0; }
  .track { flex: 1; height: 8px; background: #e2e8f0; border-radius: 9999px; overflow: hidden; }
  .fill { height: 100%; background: #3b82f6; border-radius: 9999px; }
  .row-value { width: 52px; text-align: right; font-size: 13px; color: #3b82f6; flex-shrink: 0; }
  .desc { font-size: 14px; color: #475569; }
  .cols { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 18px; }
  .col { flex: 1; min-width: 220px; background: #f8fafc; border: 1px solid #e2e8f0;
         border-radius: 8px; padding: 14px 16px; }
  .col ul { padding-left: 18px; font-size: 13px; color: #475569; }
  .col li { margin-bottom: 6px; }
  .green { color: #16a34a; } .amber { color: #d97706; } .blue { color: #2563eb; }
  .qa { border-bottom: 1px solid #e2e8f0; padding: 14px 0; }
  .qa:last-child { border-bottom: none; }
  .q-line { display: flex; align-items: flex-start; }
  .q-index { display: inline-block; min-width: 22px; height: 22px; line-height: 22px; text-align: center;
             background: #3b82f6; color: #fff; border-radius: 6px; font-size: 12px; margin-right: 8px;
             flex-shrink: 0; }
  .q-text { font-weight: 600; font-size: 14px; flex: 1; }
  .q-score { color: #16a34a; font-weight: 700; font-size: 13px; margin-left: 8px; }
  .q-block { margin-top: 8px; }
  .q-label { font-size: 12px; color: #94a3b8; margin-bottom: 2px; }
  .q-content { font-size: 13px; color: #475569; white-space: pre-wrap; }
  .q-comment { margin-top: 8px; padding: 8px 12px; background: #eff6ff;
               border-left: 3px solid #3b82f6; border-radius: 6px; font-size: 13px; color: #1d4ed8; }
  .foot { margin-top: 30px; text-align: center; color: #94a3b8; font-size: 12px; }
  @media print { body { background: #fff; padding: 0; }
                 .page { box-shadow: none; padding: 12px; } }
</style>
</head>
<body>
  <div class="page">
    <div class="title-tag">AI 面试官 · 模拟面试报告</div>
    ${headHtml}
    ${dimsHtml ? `<h2>能力评分</h2>${dimsHtml}` : ''}
    ${detailHtml}
    ${summaryHtml}
    ${questionsHtml}
    <div class="foot">本报告由 AI 面试官自动生成 · 生成于 ${new Date().toLocaleString('zh-CN')}</div>
  </div>
</body>
</html>`;

    // Blob：把 HTML 字符串包成二进制文件；createObjectURL 生成临时下载地址；
    // 建一个看不见的 <a> 触发点击下载，最后释放内存（浏览器下载三步标准写法）
    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const date = new Date().toISOString().slice(0, 10);
    // 文件名里的岗位名要去掉Windows不允许的字符（\/:*?"<>|）
    const safePosition = (data.position || '模拟面试').replace(/[\\/:*?"<>|]/g, '');
    a.href = url;
    a.download = `面试报告_${safePosition}_${date}.html`;
    a.click();
    URL.revokeObjectURL(url);
}
