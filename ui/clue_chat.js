// Guided presentation for the existing evidence fields and weighting endpoint.
// The extractor fills only facts present in the report; missing facts are asked explicitly.
let clueChatStep = 'type';
let clueChatBusy = false;
let clueChatRecap = '';
let clueChatLocationText = '';
let clueChatSelectedArea = null;
const clueTypes = {
  sighting: 'Sighting',
  camera_negative: 'Camera showed no match',
  area_searched: 'Area searched, no find'
};

function clueChatCurrentAreas() {
  const snapshot = state.suggestedPlacesAt;
  return state.run?.status === 'ready' && snapshot?.runId === state.run.id
    && snapshot.minute === state.minute && snapshot.version === state.version
    ? state.suggestedPlaces : [];
}

function clueChatAreaNumber(text) {
  const match = text.match(/\barea\s*0?([1-3])\b/i);
  return match ? Number(match[1]) : null;
}

function clueChatExplicitTimes(text) {
  const times = [];
  const pattern = /\b(\d{1,2})(?::([0-5]\d))?\s*(a\.?m\.?|p\.?m\.?)\b|\b(\d{1,2}):([0-5]\d)\b/gi;
  for (const match of text.matchAll(pattern)) {
    const meridiem = match[3]?.replaceAll('.', '').toLowerCase();
    let hour = Number(match[1] ?? match[4]);
    const minute = Number(match[2] ?? match[5] ?? 0);
    if (meridiem) {
      if (hour < 1 || hour > 12) continue;
      hour = hour % 12 + (meridiem === 'pm' ? 12 : 0);
    } else if ((hour < 13 && hour !== 0) || hour > 23) {
      // A bare 9:00 might mean morning or evening; ask rather than guess.
      continue;
    }
    times.push(`${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`);
  }
  return [...new Set(times)];
}

function clueChatApplyExplicitTimes(text) {
  const times = clueChatExplicitTimes(text);
  const type = $('evidenceType').value;
  if (type === 'sighting' && times.length === 1 && !$('sightingTime').value) {
    $('sightingTime').value = times[0]; return true;
  }
  if (type === 'area_searched' && times.length === 1 && !$('searchTime').value) {
    $('searchTime').value = times[0]; return true;
  }
  if (type === 'camera_negative' && times.length === 2 && !$('cameraFrom').value && !$('cameraTo').value) {
    $('cameraFrom').value = times[0]; $('cameraTo').value = times[1]; return true;
  }
  return false;
}

function clueChatUseArea(number) {
  const area = clueChatCurrentAreas()[number - 1];
  if (!area || area.radius_m < 10 || area.radius_m > 2000) return false;
  $('evidenceLat').value = Number(area.lat).toFixed(6);
  $('evidenceLon').value = Number(area.lon).toFixed(6);
  $('searchRadius').value = area.radius_m;
  clueChatSelectedArea = {number, minute: state.minute, version: state.version};
  requestDraw();
  return true;
}

function clueChatStatus(message, error = false) {
  const node = $('chatStatus');
  node.textContent = message;
  node.classList.toggle('error', error);
}

function clueChatMove(step, recap = '', message = '') {
  if (clueChatBusy) return;
  const turn = $('chatTurn');
  const change = () => {
    clueChatStep = step;
    clueChatRecap = recap;
    clueChatStatus('');
    renderClueChat();
    if (message) clueChatStatus(message);
  };
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) { change(); return; }
  clueChatBusy = true;
  turn.classList.add('chat-leaving');
  setTimeout(() => { clueChatBusy = false; change(); }, 170);
}

function clueChatMissing() {
  if (!$('evidenceLat').value || !$('evidenceLon').value) return 'location';
  const type = $('evidenceType').value;
  if (type === 'sighting' && !$('sightingTime').value) return 'sightingTime';
  if (type === 'camera_negative' && !$('cameraFrom').value) return 'cameraFrom';
  if (type === 'camera_negative' && !$('cameraTo').value) return 'cameraTo';
  if (type === 'area_searched' && !$('searchTime').value) return 'searchTime';
  if (type === 'area_searched' && !$('searchRadius').value) return 'searchRadius';
  return 'review';
}

function clueChatAfterPin() {
  if (clueChatStep === 'location' && $('evidenceLat').value && $('evidenceLon').value)
    clueChatMove(clueChatMissing(), 'Location pinned on the map');
  else renderClueChat();
}

function resetClueChat() {
  state.editingId = null;
  $('evidenceForm').reset();
  $('evidenceLat').value = '';
  $('evidenceLon').value = '';
  $('searchRadius').value = '';
  showKindFields();
  clueChatStep = 'type';
  clueChatRecap = '';
  clueChatLocationText = '';
  clueChatSelectedArea = null;
  clueChatStatus('');
  renderClueChat();
}

function clueChatQuestion(title, hint = '') {
  const turn = $('chatTurn');
  turn.replaceChildren();
  turn.classList.remove('chat-leaving');
  const bubble = document.createElement('div');
  bubble.className = 'chat-question';
  const marker = document.createElement('span');
  marker.className = 'chat-speaker';
  marker.textContent = 'SIM2FIND';
  const heading = document.createElement('h3');
  heading.textContent = title;
  heading.tabIndex = -1;
  bubble.append(marker, heading);
  if (hint) {
    const copy = document.createElement('p');
    copy.textContent = hint;
    bubble.append(copy);
  }
  turn.append(bubble);
  return turn;
}

function clueChatButton(label, action, className = 'chat-next') {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = className;
  button.textContent = label;
  button.onclick = action;
  return button;
}

function clueChatAnswer(value) {
  const answer = document.createElement('div');
  answer.className = 'chat-answer';
  answer.textContent = value;
  return answer;
}

function clueChatApplyDraft(draft) {
  if (draft.type !== $('evidenceType').value) return false;
  clueChatLocationText = draft.location_text || '';
  if (draft.lat != null && draft.lon != null) {
    $('evidenceLat').value = Number(draft.lat).toFixed(6);
    $('evidenceLon').value = Number(draft.lon).toFixed(6);
    requestDraw();
  }
  if (draft.type === 'sighting' && draft.time) $('sightingTime').value = draft.time;
  if (draft.type === 'area_searched') {
    if (draft.time) $('searchTime').value = draft.time;
    if (draft.radius_m != null) $('searchRadius').value = draft.radius_m;
  }
  if (draft.type === 'camera_negative' && Array.isArray(draft.window)) {
    $('cameraFrom').value = draft.window[0] || '';
    $('cameraTo').value = draft.window[1] || '';
  }
  return true;
}

function clueChatTimeStep(turn, title, id) {
  const input = document.createElement('input');
  input.type = 'time';
  input.id = 'chatTimeInput';
  input.setAttribute('aria-label', title);
  input.value = $(id).value;
  const submit = () => {
    if (!input.value) { clueChatStatus('Enter a time to continue.', true); return; }
    $(id).value = input.value;
    clueChatMove(clueChatMissing(), input.value);
  };
  input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); submit(); } });
  turn.append(input, clueChatButton('Continue →', submit));
  input.focus();
}

function clueChatReview(turn) {
  const type = $('evidenceType').value;
  const rows = [
    ['Evidence', clueTypes[type], 'type'],
    ['Report', $('evidenceText').value.trim() || 'No written report', 'report'],
    [clueChatSelectedArea ? `Location · Area ${clueChatSelectedArea.number}` : 'Location',
      `${$('evidenceLat').value}, ${$('evidenceLon').value}`, 'location']
  ];
  if (type === 'camera_negative') {
    rows.push(['Camera from', $('cameraFrom').value, 'cameraFrom']);
    rows.push(['Camera to', $('cameraTo').value, 'cameraTo']);
  } else if (type === 'sighting') {
    rows.push(['Seen at', $('sightingTime').value, 'sightingTime']);
  } else {
    rows.push(['Search completed', $('searchTime').value, 'searchTime']);
    rows.push(['Search radius', `${$('searchRadius').value} m`, 'searchRadius']);
  }
  const list = document.createElement('div');
  list.className = 'chat-review';
  rows.forEach(([label, value, step]) => {
    const row = document.createElement('div');
    const detail = document.createElement('div');
    const small = document.createElement('small'); small.textContent = label;
    const strong = document.createElement('strong'); strong.textContent = value;
    detail.append(small, strong);
    row.append(detail, clueChatButton('Edit', () => clueChatMove(step), 'chat-edit'));
    list.append(row);
  });
  turn.append(list);
  const advanced = document.createElement('details');
  advanced.className = 'chat-assumptions';
  const summary = document.createElement('summary'); summary.textContent = 'Model assumptions';
  advanced.append(summary);
  const parameters = type === 'sighting'
    ? [['reliability', 'Chance witness is correct', 0.01, 1, 0.01], ['errorMeters', 'Location uncertainty (m)', 10, 1000, 1]]
    : type === 'camera_negative'
      ? [['cameraRange', 'Camera range (m)', 1, 500, 1], ['cameraMiss', 'Chance camera missed them', 0.01, 1, 0.01]]
      : [['searchPod', 'Chance search would detect them', 0.01, 0.99, 0.01]];
  parameters.forEach(([id, label, min, max, step]) => {
    const wrapper = document.createElement('label');
    wrapper.textContent = label;
    const input = document.createElement('input');
    input.type = 'number'; input.min = min; input.max = max; input.step = step;
    input.value = $(id).value;
    input.addEventListener('change', () => { if (input.checkValidity()) $(id).value = input.value; });
    wrapper.append(input); advanced.append(wrapper);
  });
  const explanation = document.createElement('p');
  explanation.textContent = $('weightRule').textContent;
  advanced.append(explanation);
  turn.append(advanced);
  const apply = clueChatButton(state.editingId ? 'Save evidence →' : 'Accept and update map →', async () => {
    if (!state.run || state.run.status !== 'ready') { clueChatStatus('Run the walkers before applying this clue.', true); return; }
    const invalid = [...advanced.querySelectorAll('input')].find(input => !input.checkValidity());
    if (invalid) { invalid.focus(); clueChatStatus('Check the model assumption values.', true); return; }
    try {
      const item = formEvidence();
      apply.disabled = true;
      await replaceEvidence([...state.evidence.filter(e => e.id !== item.id), item], item);
    } catch (error) { clueChatStatus(error.message, true); apply.disabled = false; }
    if ($('clueDialog').open) {
      clueChatStatus($('evidenceStatus').textContent || 'Could not apply the clue.', true);
      apply.disabled = false;
    }
  });
  apply.disabled = !state.run || state.run.status !== 'ready';
  turn.append(apply);
  if (apply.disabled) turn.append(clueChatAnswer('Run the walkers to enable this step. Your draft stays here.'));
}

function renderClueChat() {
  const step = clueChatStep;
  $('chatProgress').textContent = step === 'review' ? 'FINAL REVIEW' : step.toUpperCase().replace('CAMERAFROM', 'CAMERA START').replace('CAMERATO', 'CAMERA END').replace('SIGHTINGTIME', 'SIGHTING TIME').replace('SEARCHTIME', 'SEARCH TIME').replace('SEARCHRADIUS', 'SEARCH RADIUS');
  $('chatRecap').textContent = clueChatRecap ? `✓ ${clueChatRecap}` : '';
  $('chatRecap').hidden = !clueChatRecap;
  const questions = {
    type: ['What type of evidence do you want to add?', 'Choose the same evidence type used to update walker weights.'],
    report: ['What does the report say?', 'Write it naturally. AI will extract only stated facts; you can correct everything before applying it.'],
    location: ['Where did this happen?', $('evidenceType').value === 'area_searched'
      ? 'Choose a current ranked area, place a pin, or enter coordinates. Its displayed radius will be used for the searched circle.'
      : clueChatLocationText
      ? `The report mentioned ${clueChatLocationText}. Place a pin there, or enter verified coordinates.`
      : 'Place a pin on the map, or enter latitude and longitude. A street name alone is not a verified coordinate.'],
    sightingTime: ['When was the person seen?', 'Use Amherst local time.'],
    cameraFrom: ['When did the camera check start?', 'Use Amherst local time.'],
    cameraTo: ['When did the camera check end?', 'Use Amherst local time.'],
    searchTime: ['When was the search completed?', 'Use Amherst local time.'],
    searchRadius: ['How far around this point was searched?', 'Enter a radius in meters. Estimate it if needed, then review it.'],
    review: ['Does this evidence look right?', 'The map changes only after you accept it.']
  };
  const turn = clueChatQuestion(...questions[step]);
  if (step === 'type') {
    const choices = document.createElement('div'); choices.className = 'chat-choices';
    Object.entries(clueTypes).forEach(([value, label]) => choices.append(clueChatButton(label + ' ↗', () => {
      if ($('evidenceType').value !== value) {
        for (const id of ['sightingTime', 'cameraFrom', 'cameraTo', 'searchTime', 'searchRadius']) $(id).value = '';
        if (clueChatSelectedArea) {
          $('evidenceLat').value = '';
          $('evidenceLon').value = '';
          clueChatSelectedArea = null;
        }
      }
      $('evidenceType').value = value; showKindFields(); clueChatMove('report', label);
    }, 'chat-choice')));
    turn.append(choices);
  } else if (step === 'report') {
    const textarea = document.createElement('textarea');
    textarea.rows = 4; textarea.maxLength = 500; textarea.placeholder = 'Describe the evidence in your own words…';
    textarea.value = $('evidenceText').value;
    textarea.setAttribute('aria-label', 'Evidence report');
    turn.append(textarea);
    const next = clueChatButton('Extract and continue →', async () => {
      $('evidenceText').value = textarea.value.trim();
      if (!$('evidenceText').value) { clueChatStatus('Describe the evidence, or choose Skip report.', true); return; }
      next.disabled = true; clueChatStatus('Reading the report…');
      const areaNumber = $('evidenceType').value === 'area_searched'
        ? clueChatAreaNumber($('evidenceText').value) : null;
      let matched = false;
      let extractionError = false;
      try {
        const extractionText = `Evidence type selected by user: ${clueTypes[$('evidenceType').value]}. Report: ${$('evidenceText').value}`;
        const result = await api('/api/extract', {method: 'POST', body: JSON.stringify({text: extractionText})});
        matched = clueChatApplyDraft(result.draft);
      } catch (error) {
        extractionError = true;
      }
      const timeRecovered = clueChatApplyExplicitTimes($('evidenceText').value);
      const areaResolved = areaNumber && clueChatUseArea(areaNumber);
      if (areaNumber && !areaResolved && clueChatSelectedArea) {
        $('evidenceLat').value = '';
        $('evidenceLon').value = '';
        $('searchRadius').value = '';
        clueChatSelectedArea = null;
      }
      const message = areaNumber && !areaResolved
        ? `Area ${areaNumber} is not available for the current estimate. Load the current areas or place a pin.`
        : extractionError ? (timeRecovered ? 'Time read from the report. Answer the remaining questions manually.'
          : 'AI extraction unavailable. Answer the remaining questions manually.')
          : matched ? '' : 'AI could not match this report to the selected evidence type. Confirm the details manually.';
      clueChatMove(clueChatMissing(), areaResolved ? `Area ${areaNumber} selected`
        : matched ? 'Report reviewed by AI' : 'Report saved', message);
    });
    turn.append(next, clueChatButton('Skip report', () => {
      $('evidenceText').value = ''; clueChatMove(clueChatMissing(), 'Manual details');
    }, 'chat-text-button'));
    turn.append(clueChatButton('Keep as note instead', () => {
      $('evidenceText').value = textarea.value.trim();
      if (!$('evidenceText').value) return;
      $('saveNote').click(); resetClueChat(); $('clueDialog').close();
    }, 'chat-text-button'));
    textarea.focus();
  } else if (step === 'location') {
    if ($('evidenceType').value === 'area_searched') {
      const areas = clueChatCurrentAreas();
      if (areas.length) {
        const choices = document.createElement('div'); choices.className = 'chat-choices';
        areas.forEach((area, index) => {
          if (area.radius_m < 10 || area.radius_m > 2000) return;
          choices.append(clueChatButton(`Area ${index + 1} · ${area.radius_m} m radius ↗`, () => {
            if (!clueChatUseArea(index + 1)) {
              clueChatStatus('The area rankings changed. Load the current areas and choose again.', true);
              return;
            }
            clueChatMove(clueChatMissing(), `Area ${index + 1} selected`);
          }, 'chat-choice'));
        });
        turn.append(choices);
      } else if (state.run?.status === 'ready') {
        turn.append(clueChatButton('Load current search areas ↗', async () => {
          clueChatStatus('Loading the ranked areas…');
          await updateSummary();
          renderClueChat();
          if (!clueChatCurrentAreas().length) clueChatStatus('No ranked areas are available at this time. Use a map pin instead.', true);
        }, 'chat-pin'));
      }
    }
    const input = document.createElement('input');
    input.type = 'text'; input.placeholder = $('evidenceType').value === 'area_searched' ? 'Area 2 or 42.370940, -72.534660' : '42.370940, -72.534660';
    input.inputMode = 'decimal';
    input.setAttribute('aria-label', $('evidenceType').value === 'area_searched' ? 'Area number or latitude and longitude' : 'Latitude and longitude');
    if ($('evidenceLat').value && $('evidenceLon').value) input.value = `${$('evidenceLat').value}, ${$('evidenceLon').value}`;
    const useCoordinates = () => {
      if ($('evidenceType').value === 'area_searched') {
        const areaNumber = clueChatAreaNumber(input.value.trim());
        if (areaNumber) {
          if (!clueChatUseArea(areaNumber)) {
            clueChatStatus(`Area ${areaNumber} is not available for the current estimate. Use a map pin or load the ranked areas.`, true);
            return;
          }
          clueChatMove(clueChatMissing(), `Area ${areaNumber} selected`);
          return;
        }
      }
      const match = input.value.trim().match(/^(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)$/);
      if (!match || Math.abs(Number(match[1])) > 90 || Math.abs(Number(match[2])) > 180) {
        clueChatStatus('Enter valid latitude, longitude, or use the map pin.', true); return;
      }
      $('evidenceLat').value = Number(match[1]).toFixed(6);
      $('evidenceLon').value = Number(match[2]).toFixed(6);
      if (clueChatSelectedArea) { $('searchRadius').value = ''; clueChatSelectedArea = null; }
      requestDraw(); clueChatMove(clueChatMissing(), 'Coordinates set');
    };
    input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); useCoordinates(); } });
    turn.append(input, clueChatButton('Use these coordinates →', useCoordinates));
    const pin = clueChatButton('Place a pin on the map ↗', () => {
      if (clueChatSelectedArea) { $('searchRadius').value = ''; clueChatSelectedArea = null; }
      reopenClueAfterPin = true; $('clueDialog').close(); setPick('evidence');
      $('pinHint').textContent = 'Click the evidence location on the map. Press Escape to return.';
    }, 'chat-pin');
    turn.append(pin); input.focus();
  } else if (step === 'searchRadius') {
    const input = document.createElement('input');
    input.type = 'number'; input.min = 10; input.max = 2000; input.step = 1;
    input.placeholder = 'e.g. 150'; input.value = $('searchRadius').value;
    input.setAttribute('aria-label', 'Search radius in meters');
    const submit = () => {
      if (!input.value || !input.checkValidity()) { clueChatStatus('Enter a radius from 10 to 2,000 meters.', true); return; }
      $('searchRadius').value = input.value; clueChatMove(clueChatMissing(), `${input.value} m searched`);
    };
    input.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); submit(); } });
    turn.append(input, clueChatButton('Continue →', submit)); input.focus();
  } else if (step === 'review') {
    clueChatReview(turn);
  } else {
    clueChatTimeStep(turn, questions[step][0], step);
  }
  if (step !== 'type' && step !== 'review') {
    const previous = step === 'report' ? 'type'
      : step === 'cameraTo' ? 'cameraFrom'
        : step === 'searchRadius' ? 'searchTime' : 'report';
    turn.append(clueChatButton('← Back', () => clueChatMove(previous), 'chat-text-button'));
  }
  if ($('clueDialog').open) {
    if (step === 'type') turn.querySelector('.chat-choice')?.focus();
    if (step === 'review') turn.querySelector('.chat-question h3')?.focus();
  }
}

renderClueChat();
