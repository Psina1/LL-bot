import fs from "node:fs";
import path from "node:path";

const [templatePath, reportPath, outputPath] = process.argv.slice(2);
if (!templatePath || !reportPath || !outputPath) {
  console.error("Usage: node build_bot_dashboard.mjs <template.html> <report.json> <output.html>");
  process.exit(1);
}

const report = JSON.parse(fs.readFileSync(reportPath, "utf8"));
let html = fs.readFileSync(templatePath, "utf8");
const kpis = report.kpis;
const percent = (value, total) => total ? Math.round(value / total * 100) : 0;

html = html.replace(
  /<strong>\d{4}-\d{2}-\d{2} — \d{4}-\d{2}-\d{2}<\/strong>/,
  `<strong>${report.meta.periodStart} — ${report.meta.periodEnd}</strong>`,
);
html = html.replace(
  /<div class="stamp">Сформировано: .*? МСК<\/div>/,
  `<div class="stamp">Сформировано: ${report.meta.generatedAtMsk} МСК</div>`,
);

const kpiSection = `
      <section class="kpis">
        <div class="kpi"><span class="kpi-label">Участники с доступом</span><strong>${kpis.allowedParticipants}</strong><small>без администраторов</small></div>
        <div class="kpi"><span class="kpi-label">Зашли в бота</span><strong>${kpis.registeredParticipants}</strong><small>${percent(kpis.registeredParticipants, kpis.allowedParticipants)}% списка</small></div>
        <div class="kpi"><span class="kpi-label">Не заходили</span><strong class="alert">${kpis.neverEntered}</strong><small>ещё не нажали /start</small></div>
        <div class="kpi"><span class="kpi-label">Задали вопросы</span><strong>${kpis.participantsWithQuestions}</strong><small>${kpis.naturalQuestions} вопросов</small></div>
        <div class="kpi"><span class="kpi-label">Нажатий кнопок</span><strong>${kpis.participantClicks}</strong><small>действия участников</small></div>
        <div class="kpi"><span class="kpi-label">Уведомления включены</span><strong>${kpis.notificationsEnabled}</strong><small>из ${kpis.allowedParticipants}</small></div>
      </section>`;
html = html.replace(/      <section class="kpis">[\s\S]*?      <\/section>/, kpiSection);

const contentCard = `
        <article class="panel span-3" id="content">
          <h2>Контент и RAG</h2>
          <div class="distribution">
            <div class="dist-row"><span>Документы</span><div class="track"><div class="fill" style="width:100%"></div></div><b>${kpis.documentCount}</b></div>
            <div class="dist-row"><span>Чанки</span><div class="track"><div class="fill" style="width:100%"></div></div><b>${kpis.chunkCount}</b></div>
            <div class="dist-row"><span>Домашки</span><div class="track"><div class="fill" style="width:100%"></div></div><b>${kpis.homeworkCount}</b></div>
            <div class="dist-row"><span>Медиа</span><div class="track"><div class="fill" style="width:100%"></div></div><b>${kpis.mediaCount}</b></div>
          </div>
        </article>`;
html = html.replace(
  /        <article class="panel span-3" id="content">[\s\S]*?        <\/article>/,
  contentCard,
);

if (!html.includes('data-scroll="feedback-surveys"')) {
  html = html.replace(
    '        <button data-scroll="content">Контент и RAG</button>',
    '        <button data-scroll="content">Контент и RAG</button>\n        <button data-scroll="feedback-surveys">Обратная связь</button>',
  );
}

const feedbackSection = `
      <section class="section panel" id="feedback-surveys">
        <div class="section-head">
          <div><h2>Обратная связь по занятиям</h2><p>Кампании, оценки и открытые ответы участников</p></div>
          <div class="muted">${kpis.feedbackCampaignCount} кампаний · ${kpis.feedbackCompletedCount} завершённых анкет</div>
        </div>
        <div class="feedback-kpis">
          <div><span>Получателей</span><b>${kpis.feedbackResponseCount}</b></div>
          <div><span>Завершили</span><b>${kpis.feedbackCompletedCount}</b></div>
          <div><span>Не были</span><b>${kpis.feedbackNotAttendedCount}</b></div>
          <div><span>Отказались</span><b>${kpis.feedbackDeclinedCount}</b></div>
        </div>
        <h3 class="subheading">Кампании</h3>
        <div class="table-wrap">
          <table style="min-width:980px">
            <thead><tr><th>ID</th><th>Занятие</th><th>Режим</th><th>Статус</th><th>Отправлено</th><th>Завершили</th><th>Не были</th><th>Средняя полезность</th><th>Средняя оценка экспертов</th></tr></thead>
            <tbody id="feedbackCampaignsBody"></tbody>
          </table>
        </div>
        <h3 class="subheading">Ответы</h3>
        <div class="table-wrap">
          <table style="min-width:1100px">
            <thead><tr><th>Участник</th><th>Занятие</th><th>Статус</th><th>Оценки</th><th>Что было ценным</th><th>Что стоит улучшить</th><th>Завершено</th></tr></thead>
            <tbody id="feedbackResponsesBody"></tbody>
          </table>
        </div>
      </section>`;

if (html.includes('id="feedback-surveys"')) {
  html = html.replace(
    /      <section class="section panel" id="feedback-surveys">[\s\S]*?      <\/section>/,
    feedbackSection,
  );
} else {
  html = html.replace(
    '      <section class="section panel">\n        <div class="section-head">\n          <div><h2>Не заходили в бота</h2>',
    `${feedbackSection}\n\n      <section class="section panel">\n        <div class="section-head">\n          <div><h2>Не заходили в бота</h2>`,
  );
}

if (!html.includes(".feedback-kpis")) {
  html = html.replace(
    "  </style>",
    `    .feedback-kpis { display:grid; grid-template-columns:repeat(4,minmax(120px,1fr)); gap:10px; margin:4px 0 20px; }
    .feedback-kpis div { padding:14px 16px; border:1px solid var(--line); border-radius:11px; background:var(--soft-green); }
    .feedback-kpis span { display:block; color:var(--muted); font-size:12px; margin-bottom:6px; }
    .feedback-kpis b { font:700 25px "Palatino Linotype", Georgia, serif; color:var(--green); }
    .subheading { margin:22px 0 10px; font-size:17px; }
    @media (max-width: 760px) { .feedback-kpis { grid-template-columns:repeat(2,1fr); } }
  </style>`,
  );
}

const reportStart = html.indexOf("    const REPORT = ");
const reportEnd = html.indexOf(";\n    const qs", reportStart);
if (reportStart === -1 || reportEnd === -1) {
  throw new Error("REPORT marker was not found in dashboard template");
}
html = `${html.slice(0, reportStart)}    const REPORT = ${JSON.stringify(report)}${html.slice(reportEnd)}`;

if (!html.includes("function renderFeedback()")) {
  const feedbackScript = `
    function feedbackStatusBadge(status) {
      const labels = {
        completed: 'завершён',
        in_progress: 'в процессе',
        pending: 'ожидает',
        not_attended: 'не был',
        declined: 'отказался',
        active: 'активен',
        closed: 'закрыт',
        scheduled: 'запланирован',
        draft: 'черновик'
      };
      const type = status === 'completed' || status === 'active' ? 'ok'
        : status === 'declined' || status === 'not_attended' ? 'bad'
        : status === 'pending' || status === 'scheduled' ? 'warn' : 'neutral';
      return badge(labels[status] || status || '—', type);
    }

    function renderFeedback() {
      qs('#feedbackCampaignsBody').innerHTML = REPORT.feedbackCampaigns.map(campaign => {
        const mode = campaign.is_test ? badge('тест', 'warn') : badge('участники', 'ok');
        const usefulness = campaign.usefulness_avg ?? '—';
        const experts = campaign.experts_avg ?? '—';
        return '<tr><td>' + campaign.id + '</td><td><b>' + esc(campaign.lesson_title) + '</b><br><span class="muted">' +
          esc(campaign.lesson_date || '') + '</span></td><td>' + mode + '</td><td>' + feedbackStatusBadge(campaign.status) +
          '</td><td>' + (campaign.initial_sent_count || 0) + ' / ' + (campaign.recipient_count || 0) +
          '</td><td>' + (campaign.completed_count || 0) + '</td><td>' + (campaign.not_attended_count || 0) +
          '</td><td>' + usefulness + ' / 5</td><td>' + experts + ' / 5</td></tr>';
      }).join('') || '<tr><td colspan="9" class="empty">Опросы ещё не запускались</td></tr>';

      qs('#feedbackResponsesBody').innerHTML = REPORT.feedbackResponses.map(response => {
        const identity = '<b>' + esc(response.user_name) + '</b><br><span class="muted">' +
          esc(response.username ? '@' + String(response.username).replace(/^@/, '') : response.telegram_id) + '</span>';
        const scores = (response.usefulness_score ?? '—') + ' / ' + (response.experts_score ?? '—');
        return '<tr><td>' + identity + '</td><td>' + esc(response.lesson_title) + '</td><td>' +
          feedbackStatusBadge(response.status) + '</td><td>' + scores + '</td><td>' +
          esc(response.valuable_answer || '—') + '</td><td>' + esc(response.improvement_answer || '—') +
          '</td><td>' + esc(response.completedAtMsk || '—') + '</td></tr>';
      }).join('') || '<tr><td colspan="7" class="empty">Ответов пока нет</td></tr>';
    }
    renderFeedback();
`;
  html = html.replace(
    "    document.querySelectorAll('[data-scroll]')",
    `${feedbackScript}\n    document.querySelectorAll('[data-scroll]')`,
  );
}

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, html, "utf8");
console.log(JSON.stringify({
  output: outputPath,
  generatedAt: report.meta.generatedAtMsk,
  campaigns: report.feedbackCampaigns.length,
  feedbackResponses: report.feedbackResponses.length,
}));
