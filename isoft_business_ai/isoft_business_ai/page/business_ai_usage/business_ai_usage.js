// What the assistant has cost, who spent it, and the caps that stop it.
//
// Every figure here is read back from the token usage stored on each answer,
// including the cached portion — reading input_tokens alone understates the
// bill by whatever the cache served, which on this install is most of it.
//
// The controls are real: they write to Isoft Business AI Settings and are
// enforced in the ask path before the model is called.

frappe.pages['business-ai-usage'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Business AI Usage'),
		single_column: true,
	});
	frappe.pages['business-ai-usage'].instance = new UsagePage(page);
};

frappe.pages['business-ai-usage'].on_page_show = function () {
	$(document.body).addClass('full-width ibai-fullpage');
	const inst = frappe.pages['business-ai-usage'].instance;
	if (inst) inst.load();
};

$(document).on('page-change', function () {
	if ((frappe.get_route() || [])[0] !== 'business-ai-usage') {
		$(document.body).removeClass('full-width ibai-fullpage');
	}
});

/** Thousands-grouped integer. frappe.format(n, {fieldtype:'Int'}) returns a
 *  wrapping <div> for alignment, which renders as literal markup anywhere the
 *  value is set as text. */
function fmtInt(n) {
	const v = Math.round(Number(n) || 0);
	try {
		return v.toLocaleString(undefined, { maximumFractionDigits: 0 });
	} catch (e) {
		return String(v);
	}
}

const RANGES = [
	{ key: '7', label: __('7 days'), days: 6 },
	{ key: '30', label: __('30 days'), days: 29 },
	{ key: '90', label: __('90 days'), days: 89 },
	{ key: 'mtd', label: __('This month'), days: null },
];

class UsagePage {
	constructor(page) {
		this.page = page;
		this.range = '30';
		this.data = null;
		this.render();
		this.bind();
	}

	/* ------------------------------------------------------------- markup */

	render() {
		const ico = isoft_business_ai.icon;
		this.page.main.html(
			'<div class="ibai-console ibu">' +
				'<main class="ibai-main">' +
					'<div class="ibai-main-top">' +
						'<span class="ibai-brand-mark ibu-mark">' +
							isoft_business_ai.galaxy(20) + '</span>' +
						'<div class="ibai-main-title">' + __('Assistant usage') + '</div>' +
						'<div class="ibu-ranges"></div>' +
						'<a class="ibai-ico ibai-back" href="/app/business-assistant" ' +
							'title="' + __('Open the assistant') + '">' +
							ico('<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>') +
							'</a>' +
						'<a class="ibai-ico" href="/app" title="' + __('Back to ERP') + '">' +
							ico('<path d="M3 11.5 12 4l9 7.5M5.5 9.8V20h13V9.8"/>') + '</a>' +
					'</div>' +
					'<div class="ibai-body"><div class="ibai-stream ibu-body">' +
						'<div class="ibu-loading">' + __('Reading usage…') + '</div>' +
					'</div></div>' +
				'</main>' +
			'</div>'
		);
		this.$body = this.page.main.find('.ibu-body');
		const $r = this.page.main.find('.ibu-ranges');
		RANGES.forEach(r => {
			$('<button class="ibu-range"></button>')
				.text(r.label).attr('data-key', r.key)
				.toggleClass('active', r.key === this.range)
				.on('click', () => { this.range = r.key; this.paintRanges(); this.load(); })
				.appendTo($r);
		});
	}

	paintRanges() {
		this.page.main.find('.ibu-range').each((i, el) => {
			$(el).toggleClass('active', $(el).attr('data-key') === this.range);
		});
	}

	bind() {
		// nothing global; controls are wired when they are drawn
	}

	window() {
		const today = frappe.datetime.get_today();
		const r = RANGES.find(x => x.key === this.range);
		if (r && r.days === null) {
			return { from_date: frappe.datetime.month_start(), to_date: today };
		}
		return { from_date: frappe.datetime.add_days(today, -(r ? r.days : 29)), to_date: today };
	}

	/* --------------------------------------------------------------- load */

	load() {
		const w = this.window();
		frappe.call({
			method: 'isoft_business_ai.api.usage_overview',
			args: w,
			callback: r => {
				this.data = r.message;
				this.paint();
			},
			error: () => {
				this.$body.html('<div class="ibu-loading">' +
					__('Usage could not be read. You need the System Manager role to see it.') +
					'</div>');
			},
		});
	}

	/* -------------------------------------------------------------- paint */

	paint() {
		const d = this.data;
		if (!d) return;
		const t = d.total;
		this.$body.empty();

		if (!t.questions) {
			this.$body.append($('<div class="ibu-loading"></div>').text(
				__('No questions were asked between {0} and {1}.', [d.from_date, d.to_date])));
			this.$body.append(this.controls());
			return;
		}

		this.$body.append(this.tiles(t, d));
		this.$body.append(this.daily(d.by_day));
		this.$body.append(this.controls());

		this.$body.append(this.table(__('By user'), d.by_user, [
			{ k: 'user', label: __('User') },
			{ k: 'questions', label: __('Questions'), num: 1 },
			{ k: 'tokens', label: __('Tokens'), num: 1 },
			{ k: 'cache_pct', label: __('Cached %'), num: 1 },
			{ k: 'cost', label: __('Cost (USD)'), num: 1, money: 1 },
			{ k: 'cost_per_question', label: __('Per question'), num: 1, money: 1 },
		]));

		this.$body.append(this.table(__('By model'), d.by_model, [
			{ k: 'model', label: __('Model') },
			{ k: 'questions', label: __('Questions'), num: 1 },
			{ k: 'fresh', label: __('Fresh input'), num: 1 },
			{ k: 'cached', label: __('Cached input'), num: 1 },
			{ k: 'output', label: __('Output'), num: 1 },
			{ k: 'cost', label: __('Cost (USD)'), num: 1, money: 1 },
		]));

		this.$body.append(this.table(__('Tools used'), d.by_tool, [
			{ k: 'tool', label: __('Tool') },
			{ k: 'calls', label: __('Calls'), num: 1 },
			{ k: 'rows', label: __('Rows returned'), num: 1 },
			{ k: 'avg_ms', label: __('Avg ms'), num: 1 },
			{ k: 'errors', label: __('Errors'), num: 1 },
		], __('Tool calls are logged separately from answers, so this covers every call in the window including those from conversations outside it.')));

		this.$body.append(this.conversations(d.by_conversation));
	}

	tiles(t, d) {
		const $w = $('<div class="ibu-tiles"></div>');
		const tile = (k, v, n, flag) => $(
			'<div class="ibu-tile ' + (flag || '') + '"><div class="k"></div>' +
			'<div class="v"></div><div class="n"></div></div>')
			.find('.k').text(k).end().find('.v').text(v).end().find('.n').text(n || '').end();

		$w.append(tile(__('Questions'), fmtInt(t.questions),
			d.from_date + ' → ' + d.to_date));
		$w.append(tile(__('Cost'), '$' + t.cost.toFixed(4),
			'$' + t.cost_per_question.toFixed(4) + ' ' + __('per question')));
		$w.append(tile(__('Tokens'), fmtInt(t.tokens),
			fmtInt(t.output) + ' ' + __('output')));
		$w.append(tile(__('Served from cache'),
			(t.cache_pct == null ? '—' : t.cache_pct + '%'),
			__('of input tokens, at a tenth the price'),
			t.cache_pct != null && t.cache_pct > 60 ? 'ok' : ''));
		$w.append(tile(__('This month'), '$' + d.month.cost.toFixed(4),
			d.limits.monthly_budget_usd
				? __('of a ${0} budget', [d.limits.monthly_budget_usd])
				: __('no budget set'),
			d.limits.monthly_budget_usd && d.month.cost >= d.limits.monthly_budget_usd
				? 'stop' : ''));
		$w.append(tile(__('Assistant'), d.limits.enabled ? __('On') : __('Off'),
			(d.limits.model || '') + ' · ' + (d.limits.provider || ''),
			d.limits.enabled ? 'ok' : 'stop'));

		if (t.unpriced) {
			$w.append($('<div class="ibu-warn"></div>').text(__(
				'{0} answer(s) came from a model with no price on file, so their cost reads as zero.',
				[t.unpriced])));
		}
		if (d.model_assumed) {
			$w.append($('<div class="ibu-note"></div>').text(__(
				'Answers recorded before the model was stored per message are costed at the configured model, {0}.',
				[d.model_assumed])));
		}
		return $w;
	}

	/** A plain CSS bar per day. Deliberately not a charting library: an
	 *  animated container makes frappe-charts throw from its ResizeObserver. */
	daily(days) {
		const $s = this.section(__('Cost per day'));
		if (!days.length) return $s;
		const max = Math.max.apply(null, days.map(d => d.cost)) || 1;
		const $chart = $('<div class="ibu-chart"></div>');
		days.forEach(d => {
			const pct = Math.max(2, Math.round(d.cost / max * 100));
			$('<div class="ibu-bar"></div>')
				.attr('title', d.day + ' · $' + d.cost.toFixed(4) + ' · ' +
					d.questions + ' ' + __('questions'))
				.append($('<span></span>').css('height', pct + '%'))
				.append($('<i></i>').text(d.day.slice(5)))
				.appendTo($chart);
		});
		$s.append($chart);
		return $s;
	}

	controls() {
		const l = (this.data && this.data.limits) || {};
		const $s = this.section(__('Limits'),
			__('Checked before the model is called, so a user who is over a cap costs nothing. 0 means no limit.'));
		const $form = $('<div class="ibu-form"></div>');

		const field = (key, label, value, hint) => {
			const $f = $('<label class="ibu-field"><span></span>' +
				'<input type="number" min="0" step="any"></label>');
			$f.find('span').text(label);
			$f.find('input').val(value || 0).attr('data-key', key);
			if (hint) $f.append($('<i></i>').text(hint));
			return $f;
		};
		$form.append(field('daily_question_limit', __('Questions per user per day'),
			l.daily_question_limit, __('resets at midnight')));
		$form.append(field('daily_token_limit', __('Tokens per user per day'),
			l.daily_token_limit, __('fresh + cached + output')));
		$form.append(field('monthly_budget_usd', __('Monthly budget (USD)'),
			l.monthly_budget_usd, __('whole site, calendar month')));

		const $toggle = $('<label class="ibu-field ibu-switch"><span></span>' +
			'<input type="checkbox"></label>');
		$toggle.find('span').text(__('Assistant enabled'));
		$toggle.find('input').prop('checked', !!l.enabled);
		$form.append($toggle);

		const $save = $('<button class="ibu-save"></button>').text(__('Save limits'));
		const $msg = $('<span class="ibu-saved"></span>');
		$save.on('click', () => {
			const args = { enabled: $toggle.find('input').prop('checked') ? 1 : 0 };
			$form.find('input[data-key]').each((i, el) => {
				args[$(el).attr('data-key')] = $(el).val() || 0;
			});
			$save.prop('disabled', true);
			frappe.call({
				method: 'isoft_business_ai.api.save_limits',
				args: args,
				callback: () => {
					$save.prop('disabled', false);
					$msg.text(__('Saved')).addClass('is-on');
					setTimeout(() => $msg.text('').removeClass('is-on'), 2500);
					this.load();
				},
				error: () => $save.prop('disabled', false),
			});
		});
		$form.append($('<div class="ibu-actions"></div>').append($save, $msg));
		$s.append($form);
		return $s;
	}

	table(title, rows, cols, note) {
		const $s = this.section(title, note);
		if (!rows || !rows.length) {
			$s.append($('<div class="ibu-empty"></div>').text(__('Nothing in this window.')));
			return $s;
		}
		const esc = isoft_business_ai.esc;
		const head = cols.map(c =>
			'<th class="' + (c.num ? 'ibai-num' : '') + '">' + esc(c.label) + '</th>').join('');
		const body = rows.map(r => '<tr>' + cols.map(c => {
			let v = r[c.k];
			if (c.money) v = '$' + Number(v || 0).toFixed(4);
			else if (c.num && typeof v === 'number') v = fmtInt(v);
			else if (v == null || v === '') v = '—';
			return '<td class="' + (c.num ? 'ibai-num' : '') + '">' + esc(String(v)) + '</td>';
		}).join('') + '</tr>').join('');
		$s.append('<div class="ibai-result is-sheet"><div class="ibai-table-wrap">' +
			'<table class="ibai-table"><thead><tr>' + head + '</tr></thead>' +
			'<tbody>' + body + '</tbody></table></div></div>');
		return $s;
	}

	conversations(rows) {
		const $s = this.section(__('Conversations'),
			__('Click one to read it with the tokens and cost of every answer.'));
		if (!rows.length) {
			$s.append($('<div class="ibu-empty"></div>').text(__('Nothing in this window.')));
			return $s;
		}
		const $list = $('<div class="ibu-convos"></div>');
		rows.forEach(c => {
			const $row = $('<button class="ibu-convo"></button>');
			$('<span class="t"></span>')
				.text(isoft_business_ai.stripMentions(c.title)).appendTo($row);
			$('<span class="u"></span>').text(c.user || '').appendTo($row);
			$('<span class="q"></span>').text(c.questions + ' ' + __('answers')).appendTo($row);
			$('<span class="k"></span>').text(
				fmtInt(c.tokens) + ' ' + __('tokens')).appendTo($row);
			$('<span class="c"></span>').text('$' + c.cost.toFixed(4)).appendTo($row);
			$row.on('click', () => this.openConversation(c.conversation));
			$list.append($row);
		});
		$s.append($list);
		return $s;
	}

	openConversation(name) {
		frappe.call({
			method: 'isoft_business_ai.api.usage_conversation',
			args: { name },
			callback: r => {
				const d = r.message;
				if (!d) return;
				const $html = $('<div class="ibu-transcript"></div>');
				$('<div class="ibu-tmeta"></div>').text(
					(d.owner || '') + ' · ' + (d.company || '')).appendTo($html);
				d.messages.forEach(m => {
					const $t = $('<div class="ibu-turn"></div>').addClass('r-' + m.role);
					$('<div class="who"></div>').text(
						m.role === 'user' ? __('Asked') : __('Answered')).appendTo($t);
					$('<div class="body"></div>')
						.html(isoft_business_ai.format_text(m.content || '')).appendTo($t);
					if (m.tools && m.tools.length) {
						$('<div class="tools"></div>').text(
							m.tools.map(x => x.tool + ' (' + x.rows + ' rows, ' + x.ms + 'ms)').join('  ·  ')
						).appendTo($t);
					}
					if (m.role === 'assistant') {
						$('<div class="cost"></div>').text(
							(m.model || '?') + '  ·  ' +
							m.fresh + ' ' + __('fresh') + '  ·  ' +
							m.cached + ' ' + __('cached') + '  ·  ' +
							m.output + ' ' + __('output') + '  ·  $' +
							Number(m.cost || 0).toFixed(5) +
							(m.priced ? '' : '  ·  ' + __('model not priced'))
						).appendTo($t);
					}
					$html.append($t);
				});
				const dlg = new frappe.ui.Dialog({
					title: isoft_business_ai.stripMentions(d.title),
					size: 'large',
					fields: [{ fieldtype: 'HTML' }],
				});
				dlg.fields_dict[Object.keys(dlg.fields_dict)[0]].$wrapper.append($html);
				dlg.show();
			},
		});
	}

	section(title, note) {
		const $s = $('<section class="ibu-sec"></section>');
		const $h = $('<div class="ibu-sec-head"></div>');
		$('<h3></h3>').text(title).appendTo($h);
		if (note) $('<span class="note"></span>').text(note).appendTo($h);
		$s.append($h);
		// The caller appends it; doing it here as well only worked because
		// jQuery moves an element rather than copying it.
		return $s;
	}
}
