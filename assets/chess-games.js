// @ts-check
'use strict';

/** @typedef {{game_id:number, opponent_nodes:number, colour:'white'|'black', outcome:'win'|'draw'|'loss', total_plies:number, termination:'natural'|'maximum_plies', opening_id:string, file:string}} GameEntry */

/** @type {GameEntry[]} */
let games = [];
const opponentFilter = /** @type {HTMLSelectElement} */ (document.getElementById('opponent-filter'));
const outcomeFilter = /** @type {HTMLSelectElement} */ (document.getElementById('outcome-filter'));
const colourFilter = /** @type {HTMLSelectElement} */ (document.getElementById('colour-filter'));
const sortOrder = /** @type {HTMLSelectElement} */ (document.getElementById('sort-order'));
const gameList = /** @type {HTMLTableSectionElement} */ (document.getElementById('game-list'));
const gameCount = /** @type {HTMLParagraphElement} */ (document.getElementById('game-count'));
const copyStatus = /** @type {HTMLParagraphElement} */ (document.getElementById('copy-status'));
const copyDialog = /** @type {HTMLDialogElement} */ (document.getElementById('copy-dialog'));
const copyText = /** @type {HTMLTextAreaElement} */ (document.getElementById('copy-text'));

/** @param {string} label @param {string} text @returns {HTMLTableCellElement} */
function cell(label, text) {
  const element = document.createElement('td');
  element.dataset.label = label;
  element.textContent = text;
  return element;
}

/** @param {GameEntry} game @param {HTMLButtonElement} button @returns {Promise<void>} */
async function copyGame(game, button) {
  button.disabled = true;
  const description = `Game ${game.game_id} vs ${game.opponent_nodes.toLocaleString('en-US')} nodes`;
  try {
    const response = await fetch(`/assets/chess-games/${game.file}`);
    if (!response.ok) throw new Error('PGN download failed');
    const pgn = await response.text();
    try {
      await navigator.clipboard.writeText(pgn);
      copyStatus.textContent = `${description}: PGN copied.`;
    } catch {
      copyText.value = pgn;
      copyDialog.showModal();
      copyText.focus();
      copyText.select();
      copyStatus.textContent = `${description}: copy the PGN in the open dialog.`;
    }
  } catch {
    copyStatus.textContent = `${description}: could not load the PGN. Please try its download link.`;
  } finally {
    button.disabled = false;
  }
}

/** @param {GameEntry} game @returns {HTMLTableRowElement} */
function gameRow(game) {
  const row = document.createElement('tr');
  const identity = cell('Game ID', String(game.game_id));
  if (game.game_id === 74 && game.opponent_nodes === 200000) {
    const note = document.createElement('span');
    note.className = 'featured';
    note.textContent = 'Homepage replay';
    identity.append(note);
  }
  const length = cell('Length', `${game.total_plies} half-moves`);
  const lengthNote = document.createElement('span');
  lengthNote.className = 'length-note';
  lengthNote.textContent = `Ends on move ${Math.ceil(game.total_plies / 2)}${game.termination === 'maximum_plies' ? ' · move-limit draw' : ''}`;
  length.append(lengthNote);
  const actions = cell('PGN', '');
  const group = document.createElement('div');
  group.className = 'game-actions';
  const copy = document.createElement('button');
  copy.type = 'button';
  copy.className = 'button';
  copy.textContent = 'Copy PGN';
  const identityText = `game ${game.game_id} vs ${game.opponent_nodes.toLocaleString('en-US')} nodes`;
  copy.setAttribute('aria-label', `Copy PGN for ${identityText}`);
  copy.addEventListener('click', () => { void copyGame(game, copy); });
  const download = document.createElement('a');
  download.className = 'button accent';
  download.textContent = 'Download';
  download.href = `/assets/chess-games/${game.file}`;
  download.download = game.file;
  download.setAttribute('aria-label', `Download PGN for ${identityText}`);
  group.append(copy, download);
  actions.append(group);
  row.append(identity, cell('SF nodes', game.opponent_nodes.toLocaleString('en-US')), cell('Our colour', game.colour === 'white' ? 'White' : 'Black'), cell('Our result', {win:'Win',draw:'Draw',loss:'Loss'}[game.outcome]), length, actions);
  return row;
}

/** @returns {void} */
function renderGames() {
  const selected = games.filter(game =>
    (opponentFilter.value === 'all' || game.opponent_nodes === Number(opponentFilter.value)) &&
    (outcomeFilter.value === 'all' || game.outcome === outcomeFilter.value) &&
    (colourFilter.value === 'all' || game.colour === colourFilter.value));
  selected.sort((first, second) => {
    const lengthDifference = first.total_plies - second.total_plies;
    const stableOrder = first.opponent_nodes - second.opponent_nodes || first.game_id - second.game_id;
    if (sortOrder.value === 'shortest') return lengthDifference || stableOrder;
    if (sortOrder.value === 'longest') return -lengthDifference || stableOrder;
    return stableOrder;
  });
  gameList.replaceChildren(...selected.map(gameRow));
  gameCount.textContent = selected.length ? `${selected.length} of ${games.length} games` : 'No games match these filters.';
}

/** @returns {Promise<void>} */
async function loadGames() {
  try {
    const response = await fetch('/assets/chess-games/games.json');
    if (!response.ok) throw new Error('Game index download failed');
    /** @type {{games:GameEntry[]}} */
    const manifest = await response.json();
    games = manifest.games;
    renderGames();
  } catch {
    gameCount.textContent = 'The game list could not load. Please reload or use the complete PGN download above.';
  }
}

for (const control of [opponentFilter, outcomeFilter, colourFilter, sortOrder]) {
  control.addEventListener('change', renderGames);
}
void loadGames();
