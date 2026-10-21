/**
 * NPTEL Practice Hub - Frontend Application Script
 * Phase 5: Practice Mode Implementation & Learn Mode Integration
 * Handles dashboard data, Learn Mode navigation, Practice Mode test configuration,
 * client-blind test runner, server-side grading, answer review, and mastery tracking.
 */

// Determine API base:
// If accessed on localhost/127.0.0.1 from a non-Flask port (e.g., Live Server on 5500),
// or accessed via file://, route API calls to the Flask backend at http://127.0.0.1:5000.
// If served directly by Flask (port 5000) or standard web hosting, use relative path ('').
const isCustomDevPort = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
  && window.location.port !== ''
  && window.location.port !== '5000';

const API_BASE = (isCustomDevPort || !window.location.protocol.startsWith('http'))
  ? 'http://127.0.0.1:5000'
  : '';

// Global Application State
const appState = {
  currentView: 'dashboard',    // 'dashboard' | 'learn' | 'practice'
  currentWeek: 1,              // Active week number (1-12)
  currentQuestionIndex: 0,     // 0-indexed position within the active week
  weekQuestions: [],           // Array of question objects for active week in Learn Mode
  weekMetadata: null,          // Metadata for active week (title, question count)
  allWeeks: [],                // Cached list of all 12 weeks from /api/weeks
  activeRequestToken: 0        // Request token to prevent stale race-condition overwrites
};

// Practice Mode State
const practiceState = {
  sessionId: null,
  testType: 'complete',        // 'complete' | 'quick' | 'custom'
  selectedWeeks: [1],          // Array of selected week numbers
  quickCount: 10,              // 10 | 20 | 30
  customCount: 10,             // User-entered count
  questions: [],               // Active test questions (without answers)
  currentQuestionIndex: 0,     // 0-indexed position within test
  answers: {},                 // { [questionId]: optionId }
  cachedResults: null,         // Graded results payload
  lastConfig: null             // Saved config for retaking
};

document.addEventListener('DOMContentLoaded', () => {
  initApp();
  setupEventListeners();
});

/**
 * Initializes backend connection, loads directory, checks active session, handles route
 */
async function initApp() {
  await checkHealth();
  await loadWeeks();
  checkActivePracticeSession();
  handleUrlRouting();
}

/**
 * Checks backend API health status
 */
async function checkHealth() {
  const statusDot = document.getElementById('status-dot');
  const statusText = document.getElementById('status-text');

  try {
    const response = await fetch(`${API_BASE}/api/health`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' }
    });

    if (response.ok) {
      if (statusDot) statusDot.className = 'status-dot online';
      if (statusText) statusText.textContent = 'API Connected';
    } else {
      throw new Error(`HTTP ${response.status}`);
    }
  } catch (err) {
    if (statusDot) statusDot.className = 'status-dot offline';
    if (statusText) statusText.textContent = 'API Offline';
    console.warn('Backend health check failed:', err);
  }
}

/* ==========================================================================
   Guest Identity & LocalStorage Progress Tracking
   ========================================================================== */

function getGuestClientId() {
  let clientId = localStorage.getItem('nptel_guest_client_id');
  if (!clientId) {
    if (
      typeof window !== 'undefined' &&
      window.crypto &&
      typeof window.crypto.randomUUID === 'function'
    ) {
      clientId = 'guest_' + window.crypto.randomUUID();
    } else {
      clientId =
        'guest_' + Math.random().toString(36).substring(2, 10) +
        '_' + Date.now();
    }
    localStorage.setItem('nptel_guest_client_id', clientId);
  }
  return clientId;
}

function getStoredProgress() {
  try {
    const reviewed = JSON.parse(localStorage.getItem('nptel_reviewed_questions') || '{}');
    const practiced = JSON.parse(localStorage.getItem('nptel_practiced_weeks') || '[]');
    const mastered = JSON.parse(localStorage.getItem('nptel_mastered_weeks') || '[]');
    return { reviewed, practiced, mastered };
  } catch (e) {
    return { reviewed: {}, practiced: [], mastered: [] };
  }
}

function saveStoredProgress(progress) {
  if (progress.reviewed) localStorage.setItem('nptel_reviewed_questions', JSON.stringify(progress.reviewed));
  if (progress.practiced) localStorage.setItem('nptel_practiced_weeks', JSON.stringify(progress.practiced));
  if (progress.mastered) localStorage.setItem('nptel_mastered_weeks', JSON.stringify(progress.mastered));
}

function recordLearnQuestionViewed(weekNum, questionId) {
  const progress = getStoredProgress();
  if (!progress.reviewed[weekNum]) {
    progress.reviewed[weekNum] = [];
  }
  if (!progress.reviewed[weekNum].includes(questionId)) {
    progress.reviewed[weekNum].push(questionId);
    saveStoredProgress(progress);
  }
}

function isWeekReviewed(weekNum) {
  const progress = getStoredProgress();
  const viewed = progress.reviewed[weekNum] || [];
  return viewed.length >= 10;
}

function isWeekPracticed(weekNum) {
  const progress = getStoredProgress();
  return (progress.practiced || []).includes(weekNum);
}

function isWeekMastered(weekNum) {
  const progress = getStoredProgress();
  return (progress.mastered || []).includes(weekNum);
}

/**
 * Loads course weeks directory from backend API (/api/weeks)
 */
async function loadWeeks() {
  const container = document.getElementById('weeks-container');
  const totalQuestionsPill = document.getElementById('total-questions-count');
  const weekSelect = document.getElementById('learn-week-select');
  if (!container) return;

  container.innerHTML = `
    <div class="state-box">
      <p>Loading course assignment weeks from backend...</p>
    </div>
  `;

  try {
    const response = await fetch(`${API_BASE}/api/weeks`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' }
    });

    if (!response.ok) {
      throw new Error(`Failed to load weeks: HTTP ${response.status}`);
    }

    const payload = await response.json();
    const weeks = payload.weeks || [];
    appState.allWeeks = weeks;

    if (weeks.length === 0) {
      container.innerHTML = `
        <div class="state-box">
          <p>No assignment weeks currently available.</p>
        </div>
      `;
      return;
    }

    // Update total questions in hero banner
    let grandTotalQuestions = 0;
    weeks.forEach(w => grandTotalQuestions += (w.verified_questions || w.total_questions || 0));
    if (totalQuestionsPill) {
      totalQuestionsPill.innerHTML = `<strong>${grandTotalQuestions}</strong> Questions`;
    }

    // Populate Learn Mode week selector dropdown
    if (weekSelect) {
      weekSelect.innerHTML = '';
      weeks.forEach(w => {
        const opt = document.createElement('option');
        opt.value = String(w.week_number);
        opt.textContent = `Week ${w.week_number}: ${w.title || `Assignment ${w.week_number}`}`;
        weekSelect.appendChild(opt);
      });
      weekSelect.value = String(appState.currentWeek);
    }

    // Render interactive week cards
    renderWeekCards(weeks);

    // Initialize Practice Mode weeks checkbox grid
    renderPracticeWeeksCheckboxGrid();

  } catch (err) {
    console.error('Error loading weeks:', err);
    container.innerHTML = `
      <div class="state-box error">
        <h3>Unable to Connect to Backend</h3>
        <p>Could not retrieve week assignments. Ensure the Flask server is running at <code>http://127.0.0.1:5000</code>.</p>
        <button id="btn-retry-weeks" class="btn-retry">Retry Connection</button>
      </div>
    `;

    const retryBtn = document.getElementById('btn-retry-weeks');
    if (retryBtn) {
      retryBtn.addEventListener('click', () => {
        initApp();
      });
    }
  }
}

/**
 * Renders week cards on the dashboard with Reviewed, Practiced, and Mastered progress pills
 */
function renderWeekCards(weeks) {
  const container = document.getElementById('weeks-container');
  if (!container) return;

  container.innerHTML = '';
  const grid = document.createElement('div');
  grid.className = 'weeks-grid';

  weeks.forEach(week => {
    const card = document.createElement('article');
    card.className = 'week-card clickable-week';
    card.tabIndex = 0;
    card.setAttribute('role', 'button');
    card.setAttribute('aria-label', `Study Week ${week.week_number} in Learn Mode`);

    const qCount = week.verified_questions !== undefined ? week.verified_questions : week.total_questions;

    const headDiv = document.createElement('div');
    headDiv.className = 'week-card-head';

    const weekNumSpan = document.createElement('span');
    weekNumSpan.className = 'week-number';
    weekNumSpan.textContent = `Week ${week.week_number}`;

    const countBadge = document.createElement('span');
    countBadge.className = 'question-count-badge';
    countBadge.textContent = `${qCount} Questions`;

    headDiv.appendChild(weekNumSpan);
    headDiv.appendChild(countBadge);

    const titleHeading = document.createElement('h4');
    titleHeading.className = 'week-title';
    titleHeading.textContent = week.title || `Week ${week.week_number}`;

    const ctaSpan = document.createElement('span');
    ctaSpan.className = 'week-card-cta';
    ctaSpan.textContent = 'Study in Learn Mode →';

    card.appendChild(headDiv);
    card.appendChild(titleHeading);
    card.appendChild(ctaSpan);

    // Progress Badges (Reviewed, Practiced, Mastered)
    const isRev = isWeekReviewed(week.week_number);
    const isPrac = isWeekPracticed(week.week_number);
    const isMast = isWeekMastered(week.week_number);

    if (isRev || isPrac || isMast) {
      const progDiv = document.createElement('div');
      progDiv.className = 'week-progress-pills';

      if (isMast) {
        const mPill = document.createElement('span');
        mPill.className = 'prog-pill mastered';
        mPill.textContent = '★ Mastered';
        progDiv.appendChild(mPill);
      } else if (isPrac) {
        const pPill = document.createElement('span');
        pPill.className = 'prog-pill practiced';
        pPill.textContent = 'Practiced';
        progDiv.appendChild(pPill);
      }

      if (isRev) {
        const rPill = document.createElement('span');
        rPill.className = 'prog-pill reviewed';
        rPill.textContent = 'Reviewed';
        progDiv.appendChild(rPill);
      }

      card.appendChild(progDiv);
    }

    // Card click/enter opens Learn Mode for this specific week
    card.addEventListener('click', () => {
      openLearnMode(week.week_number);
    });

    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openLearnMode(week.week_number);
      }
    });

    grid.appendChild(card);
  });

  container.appendChild(grid);
}

/* ==========================================================================
   Event Listeners Setup
   ========================================================================== */

function setupEventListeners() {
  // 1. Learn Mode card click from dashboard
  const learnCard = document.getElementById('learn-mode-card');
  const btnStartLearn = document.getElementById('btn-open-learn');

  if (learnCard) {
    learnCard.addEventListener('click', () => openLearnMode(1));
    learnCard.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openLearnMode(1);
      }
    });
  }

  if (btnStartLearn) {
    btnStartLearn.addEventListener('click', (e) => {
      e.stopPropagation();
      openLearnMode(1);
    });
  }

  // 2. Practice Mode card click from dashboard
  const practiceCard = document.getElementById('practice-mode-card');
  const btnStartPractice = document.getElementById('btn-open-practice');

  if (practiceCard) {
    practiceCard.addEventListener('click', () => openPracticeMode());
    practiceCard.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openPracticeMode();
      }
    });
  }

  if (btnStartPractice) {
    btnStartPractice.addEventListener('click', (e) => {
      e.stopPropagation();
      openPracticeMode();
    });
  }

  // 3. Back to Dashboard buttons
  const btnBackLearn = document.getElementById('btn-back-dashboard');
  if (btnBackLearn) {
    btnBackLearn.addEventListener('click', () => showDashboard());
  }

  const btnBackPractice = document.getElementById('btn-practice-back-dashboard');
  if (btnBackPractice) {
    btnBackPractice.addEventListener('click', () => showDashboard());
  }

  const btnResultsToDash = document.getElementById('btn-results-to-dashboard');
  if (btnResultsToDash) {
    btnResultsToDash.addEventListener('click', () => showDashboard());
  }

  // 4. Learn Mode Week Selector & Prev/Next
  const weekSelect = document.getElementById('learn-week-select');
  if (weekSelect) {
    weekSelect.addEventListener('change', (e) => {
      const selectedWeek = parseInt(e.target.value, 10);
      if (!isNaN(selectedWeek) && selectedWeek >= 1 && selectedWeek <= 12) {
        changeWeek(selectedWeek);
      }
    });
  }

  const btnPrev = document.getElementById('btn-prev-question');
  if (btnPrev) {
    btnPrev.addEventListener('click', () => navigateToPreviousQuestion());
  }

  const btnNext = document.getElementById('btn-next-question');
  if (btnNext) {
    btnNext.addEventListener('click', () => navigateToNextQuestion());
  }

  // 5. Practice Mode Setup Controls
  const btnSelectAll = document.getElementById('btn-select-all-weeks');
  if (btnSelectAll) {
    btnSelectAll.addEventListener('click', () => selectAllPracticeWeeks(true));
  }

  const btnDeselectAll = document.getElementById('btn-deselect-all-weeks');
  if (btnDeselectAll) {
    btnDeselectAll.addEventListener('click', () => selectAllPracticeWeeks(false));
  }

  // Test Type Radios
  document.querySelectorAll('input[name="practice_test_type"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
      practiceState.testType = e.target.value;
      updatePracticeConfigCalculations();
    });
  });

  // Quick Count Pills
  const quickContainer = document.getElementById('quick-counts-container');
  if (quickContainer) {
    quickContainer.querySelectorAll('.btn-count-pill').forEach(btn => {
      btn.addEventListener('click', (e) => {
        quickContainer.querySelectorAll('.btn-count-pill').forEach(b => b.classList.remove('active'));
        e.currentTarget.classList.add('active');
        practiceState.quickCount = parseInt(e.currentTarget.getAttribute('data-count'), 10);
        // Switch radio to quick
        const rQuick = document.getElementById('test-type-quick');
        if (rQuick) rQuick.checked = true;
        practiceState.testType = 'quick';
      });
    });
  }

  // Custom Count Input
  const customCountInput = document.getElementById('practice-custom-count');
  if (customCountInput) {
    customCountInput.addEventListener('input', (e) => {
      const val = parseInt(e.target.value, 10);
      if (!isNaN(val) && val > 0) {
        practiceState.customCount = val;
      }
      const rCustom = document.getElementById('test-type-custom');
      if (rCustom) rCustom.checked = true;
      practiceState.testType = 'custom';
    });
  }

  // Start Practice Test button
  const btnStartTest = document.getElementById('btn-start-practice-test');
  if (btnStartTest) {
    btnStartTest.addEventListener('click', () => startPracticeTest());
  }

  // Active Practice Test Prev / Next / Clear / Submit
  const btnPracticePrev = document.getElementById('btn-practice-prev');
  if (btnPracticePrev) {
    btnPracticePrev.addEventListener('click', () => navigatePracticeQuestion(-1));
  }

  const btnPracticeNext = document.getElementById('btn-practice-next');
  if (btnPracticeNext) {
    btnPracticeNext.addEventListener('click', () => navigatePracticeQuestion(1));
  }

  const btnClearAnswer = document.getElementById('btn-clear-answer');
  if (btnClearAnswer) {
    btnClearAnswer.addEventListener('click', () => clearCurrentPracticeAnswer());
  }

  const btnPracticeSubmit = document.getElementById('btn-practice-submit');
  if (btnPracticeSubmit) {
    btnPracticeSubmit.addEventListener('click', () => openSubmitConfirmModal());
  }

  // Modal Buttons
  const btnCancelSubmit = document.getElementById('btn-cancel-submit');
  if (btnCancelSubmit) {
    btnCancelSubmit.addEventListener('click', () => closeSubmitConfirmModal());
  }

  const btnConfirmSubmit = document.getElementById('btn-confirm-submit');
  if (btnConfirmSubmit) {
    btnConfirmSubmit.addEventListener('click', () => submitPracticeTest());
  }

  // Resume Banner Buttons
  const btnResume = document.getElementById('btn-resume-active-session');
  if (btnResume) {
    btnResume.addEventListener('click', () => {
      const activeId = localStorage.getItem('nptel_active_session_id');
      if (activeId) resumePracticeSession(activeId);
    });
  }

  const btnDiscard = document.getElementById('btn-discard-active-session');
  if (btnDiscard) {
    btnDiscard.addEventListener('click', () => {
      localStorage.removeItem('nptel_active_session_id');
      const banner = document.getElementById('practice-resume-banner');
      if (banner) banner.style.display = 'none';
    });
  }

  // Results Buttons: Retake / New Test
  const btnRetake = document.getElementById('btn-retake-test');
  if (btnRetake) {
    btnRetake.addEventListener('click', () => retakePracticeTest());
  }

  const btnNewTest = document.getElementById('btn-new-test');
  if (btnNewTest) {
    btnNewTest.addEventListener('click', () => {
      showPracticeSetup();
    });
  }

  // Global Keyboard Navigation (Arrows)
  window.addEventListener('keydown', (e) => {
    const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
    if (activeTag === 'select' || activeTag === 'input' || activeTag === 'textarea') return;

    if (appState.currentView === 'learn') {
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        navigateToPreviousQuestion();
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        navigateToNextQuestion();
      }
    } else if (appState.currentView === 'practice') {
      const testCard = document.getElementById('practice-test-card');
      if (testCard && testCard.style.display !== 'none') {
        if (e.key === 'ArrowLeft') {
          e.preventDefault();
          navigatePracticeQuestion(-1);
        } else if (e.key === 'ArrowRight') {
          e.preventDefault();
          navigatePracticeQuestion(1);
        }
      }
    }
  });

  // URL Popstate
  window.addEventListener('popstate', () => {
    handleUrlRouting();
  });
}

/**
 * Inspects URL hash to restore dashboard, Learn Mode, or Practice Mode
 */
function handleUrlRouting() {
  const hash = window.location.hash;
  if (hash.startsWith('#learn-week-')) {
    const weekNum = parseInt(hash.replace('#learn-week-', ''), 10);
    if (!isNaN(weekNum) && weekNum >= 1 && weekNum <= 12) {
      openLearnMode(weekNum, false);
      return;
    }
  } else if (hash === '#practice') {
    openPracticeMode(false);
    return;
  }
  showDashboard(false);
}

/**
 * Transitions view to the course dashboard
 */
function showDashboard(updateHash = true) {
  appState.currentView = 'dashboard';

  const dashboardView = document.getElementById('dashboard-view');
  const learnView = document.getElementById('learn-mode-view');
  const practiceView = document.getElementById('practice-mode-view');

  if (learnView) learnView.style.display = 'none';
  if (practiceView) practiceView.style.display = 'none';
  if (dashboardView) dashboardView.style.display = 'block';

  // Re-render week cards to refresh progress pills
  if (appState.allWeeks.length > 0) {
    renderWeekCards(appState.allWeeks);
  }

  if (updateHash && window.location.hash !== '') {
    window.history.pushState(null, '', window.location.pathname);
  }
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* ==========================================================================
   Learn Mode Implementation
   ========================================================================== */

function openLearnMode(weekNumber = 1, updateHash = true) {
  appState.currentView = 'learn';
  appState.currentWeek = weekNumber;
  appState.currentQuestionIndex = 0;

  const dashboardView = document.getElementById('dashboard-view');
  const learnView = document.getElementById('learn-mode-view');
  const practiceView = document.getElementById('practice-mode-view');
  const weekSelect = document.getElementById('learn-week-select');

  if (dashboardView) dashboardView.style.display = 'none';
  if (practiceView) practiceView.style.display = 'none';
  if (learnView) {
    learnView.style.display = 'flex';
    learnView.scrollIntoView({ behavior: 'smooth' });
  }

  if (weekSelect) {
    weekSelect.value = String(weekNumber);
  }

  if (updateHash) {
    window.history.pushState(null, '', `#learn-week-${weekNumber}`);
  }

  loadLearnQuestions(weekNumber);
}

function changeWeek(weekNumber) {
  if (weekNumber === appState.currentWeek && appState.weekQuestions.length > 0) return;

  appState.currentWeek = weekNumber;
  appState.currentQuestionIndex = 0;

  const weekSelect = document.getElementById('learn-week-select');
  if (weekSelect) {
    weekSelect.value = String(weekNumber);
  }

  window.history.pushState(null, '', `#learn-week-${weekNumber}`);
  loadLearnQuestions(weekNumber);
}

async function loadLearnQuestions(weekNumber) {
  const container = document.getElementById('learn-content-container');
  const titleElem = document.getElementById('learn-week-title');
  const countElem = document.getElementById('learn-week-question-count');
  const btnPrev = document.getElementById('btn-prev-question');
  const btnNext = document.getElementById('btn-next-question');
  const counterPill = document.getElementById('learn-question-counter');

  if (!container) return;

  const requestToken = ++appState.activeRequestToken;

  container.innerHTML = `
    <div class="state-box">
      <p>Loading Week ${weekNumber} assignment questions...</p>
    </div>
  `;

  if (titleElem) titleElem.textContent = `Week ${weekNumber}`;
  if (btnPrev) btnPrev.disabled = true;
  if (btnNext) btnNext.disabled = true;
  if (counterPill) counterPill.textContent = 'Loading...';

  try {
    const response = await fetch(`${API_BASE}/api/weeks/${weekNumber}/questions`, {
      method: 'GET',
      headers: { 'Accept': 'application/json' }
    });

    if (requestToken !== appState.activeRequestToken) return;

    if (!response.ok) {
      throw new Error(`Failed to load questions (HTTP ${response.status})`);
    }

    const payload = await response.json();
    if (payload.status !== 'success' || !Array.isArray(payload.questions)) {
      throw new Error(payload.message || 'Invalid questions response from server');
    }

    appState.weekMetadata = {
      week_number: payload.week_number,
      title: payload.title,
      total_questions: payload.total_questions
    };
    appState.weekQuestions = payload.questions;

    if (titleElem) {
      titleElem.textContent = payload.title || `Week ${weekNumber} Assignment Solutions`;
    }
    if (countElem) {
      countElem.innerHTML = `<strong>${payload.total_questions}</strong> Questions`;
    }

    if (appState.weekQuestions.length === 0) {
      container.innerHTML = `
        <div class="state-box">
          <p>No verified questions found for Week ${weekNumber}.</p>
        </div>
      `;
      if (counterPill) counterPill.textContent = '0 Questions';
      return;
    }

    appState.currentQuestionIndex = 0;
    renderCurrentQuestion();

  } catch (err) {
    if (requestToken === appState.activeRequestToken) {
      console.error(`Error loading Week ${weekNumber} questions:`, err);
      container.innerHTML = `
        <div class="state-box error">
          <h3>Failed to Load Week ${weekNumber} Questions</h3>
          <p>Unable to retrieve questions from the server. Please check your connection and retry.</p>
          <button type="button" id="btn-retry-learn" class="btn-retry">Retry Week ${weekNumber}</button>
        </div>
      `;

      const retryBtn = document.getElementById('btn-retry-learn');
      if (retryBtn) {
        retryBtn.addEventListener('click', () => {
          loadLearnQuestions(weekNumber);
        });
      }
    }
  }
}

function renderCurrentQuestion() {
  const container = document.getElementById('learn-content-container');
  const btnPrev = document.getElementById('btn-prev-question');
  const btnNext = document.getElementById('btn-next-question');
  const counterPill = document.getElementById('learn-question-counter');

  if (!container || !appState.weekQuestions || appState.weekQuestions.length === 0) return;

  const totalQuestions = appState.weekQuestions.length;
  const qIndex = appState.currentQuestionIndex;
  const question = appState.weekQuestions[qIndex];

  // Record that this question has been viewed in Learn Mode
  if (appState.currentWeek && question.id) {
    recordLearnQuestionViewed(appState.currentWeek, question.id);
  }

  if (btnPrev) btnPrev.disabled = (qIndex === 0);
  if (btnNext) btnNext.disabled = (qIndex === totalQuestions - 1);
  if (counterPill) {
    counterPill.textContent = `Question ${qIndex + 1} of ${totalQuestions}`;
  }

  container.innerHTML = '';

  const card = document.createElement('article');
  card.className = 'question-display-card';
  card.setAttribute('aria-labelledby', 'current-question-heading');

  const cardHeader = document.createElement('div');
  cardHeader.className = 'question-card-header';

  const metaGroup = document.createElement('div');
  metaGroup.className = 'question-meta-group';

  const numBadge = document.createElement('span');
  numBadge.className = 'question-number-badge';
  numBadge.id = 'current-question-heading';
  numBadge.textContent = `Question ${question.question_number}`;

  const marksBadge = document.createElement('span');
  marksBadge.className = 'question-marks-badge';
  const marksVal = (question.marks !== undefined && question.marks !== null) ? Number(question.marks).toFixed(1) : '1.0';
  marksBadge.textContent = `${marksVal} Mark`;

  metaGroup.appendChild(numBadge);
  metaGroup.appendChild(marksBadge);

  const studyTag = document.createElement('span');
  studyTag.className = 'study-mode-tag';
  studyTag.textContent = '✓ Verified Solution';

  cardHeader.appendChild(metaGroup);
  cardHeader.appendChild(studyTag);
  card.appendChild(cardHeader);

  const textBox = document.createElement('div');
  textBox.className = 'question-text-box';

  const questionP = document.createElement('p');
  questionP.className = 'question-text';
  questionP.textContent = question.question_text || '';

  textBox.appendChild(questionP);
  card.appendChild(textBox);

  const optionsContainer = document.createElement('div');
  optionsContainer.className = 'options-container';

  const optionsHeading = document.createElement('h4');
  optionsHeading.className = 'options-heading';
  optionsHeading.textContent = 'Answer Options';
  optionsContainer.appendChild(optionsHeading);

  const optionsList = document.createElement('div');
  optionsList.className = 'options-list';
  optionsList.setAttribute('role', 'list');

  const options = question.options || [];
  options.forEach(opt => {
    const isCorrect = (opt.is_correct === 1 || opt.is_correct === true);

    const optItem = document.createElement('div');
    optItem.className = isCorrect ? 'option-item option-correct' : 'option-item';
    optItem.setAttribute('role', 'listitem');
    optItem.tabIndex = 0;

    const optLeft = document.createElement('div');
    optLeft.className = 'option-left';

    const letterPill = document.createElement('span');
    letterPill.className = isCorrect ? 'option-letter-pill option-letter-correct' : 'option-letter-pill';
    letterPill.textContent = (opt.option_letter || '').toUpperCase();

    const textSpan = document.createElement('span');
    textSpan.className = 'option-text';
    textSpan.textContent = opt.option_text || '';

    optLeft.appendChild(letterPill);
    optLeft.appendChild(textSpan);
    optItem.appendChild(optLeft);

    if (isCorrect) {
      const statusBadge = document.createElement('div');
      statusBadge.className = 'option-status-badge';
      statusBadge.setAttribute('aria-label', 'Correct Answer');

      const checkIcon = document.createElement('span');
      checkIcon.className = 'check-icon';
      checkIcon.textContent = '✓';

      const labelSpan = document.createElement('span');
      labelSpan.textContent = 'Correct Answer';

      statusBadge.appendChild(checkIcon);
      statusBadge.appendChild(labelSpan);
      optItem.appendChild(statusBadge);
    }

    optionsList.appendChild(optItem);
  });

  optionsContainer.appendChild(optionsList);
  card.appendChild(optionsContainer);

  container.appendChild(card);
}

function navigateToPreviousQuestion() {
  if (appState.currentQuestionIndex > 0) {
    appState.currentQuestionIndex--;
    renderCurrentQuestion();
    window.scrollTo({ top: 120, behavior: 'smooth' });
  }
}

function navigateToNextQuestion() {
  if (appState.currentQuestionIndex < appState.weekQuestions.length - 1) {
    appState.currentQuestionIndex++;
    renderCurrentQuestion();
    window.scrollTo({ top: 120, behavior: 'smooth' });
  }
}

/* ==========================================================================
   Practice Mode Implementation
   ========================================================================== */

/**
 * Opens Practice Mode environment
 */
function openPracticeMode(updateHash = true) {
  appState.currentView = 'practice';

  const dashboardView = document.getElementById('dashboard-view');
  const learnView = document.getElementById('learn-mode-view');
  const practiceView = document.getElementById('practice-mode-view');

  if (dashboardView) dashboardView.style.display = 'none';
  if (learnView) learnView.style.display = 'none';
  if (practiceView) {
    practiceView.style.display = 'flex';
    practiceView.scrollIntoView({ behavior: 'smooth' });
  }

  if (updateHash) {
    window.history.pushState(null, '', '#practice');
  }

  // Check if active test in progress
  checkActivePracticeSession();

  // If not currently running an active test, show setup card
  if (!practiceState.sessionId) {
    showPracticeSetup();
  }
}

/**
 * Checks localStorage for an unfinished active practice session
 */
async function checkActivePracticeSession() {
  const activeSessionId = localStorage.getItem('nptel_active_session_id');
  const resumeBanner = document.getElementById('practice-resume-banner');
  const resumeText = document.getElementById('resume-banner-text');

  if (!activeSessionId) {
    if (resumeBanner) resumeBanner.style.display = 'none';
    return;
  }

  try {
    const clientId = getGuestClientId();
    const res = await fetch(`${API_BASE}/api/practice/sessions/${activeSessionId}`, {
      headers: {
        'Accept': 'application/json',
        'X-Client-ID': clientId
      }
    });

    if (res.ok) {
      const data = await res.json();
      if (data.session && data.session.status === 'active') {
        if (resumeBanner) {
          resumeBanner.style.display = 'flex';
          if (resumeText) {
            const weeksStr = (data.session.selected_weeks || []).join(', ');
            resumeText.textContent = `Unfinished ${data.session.test_type.toUpperCase()} test (${data.session.total_questions} questions from Weeks ${weeksStr}).`;
          }
        }
        return;
      } else if (data.session && (data.session.status === 'submitted' || data.session.is_submitted === 1)) {
        if (resumeBanner) {
          resumeBanner.style.display = 'flex';
          if (resumeText) {
            resumeText.textContent = `Completed ${data.session.test_type.toUpperCase()} test (${data.session.total_questions} questions). Click Resume to view results.`;
          }
        }
        return;
      }
    }

    // Definitive responses only: 404 (Not Found) or 401/403 (Unowned)
    if (res.status === 404 || res.status === 401 || res.status === 403) {
      localStorage.removeItem('nptel_active_session_id');
      if (resumeBanner) resumeBanner.style.display = 'none';
      return;
    }

    // Transient server errors (HTTP 5xx): preserve activeSessionId
    if (res.status >= 500) {
      console.warn(`Transient server error (HTTP ${res.status}) while checking active session. Preserving session ID.`);
      return;
    }
  } catch (err) {
    // Network error or offline: preserve activeSessionId
    console.warn('Network error while checking active session. Active practice session preserved across transient network error:', err);
  }
}

/**
 * Renders checkboxes for all 12 assignment weeks in Practice Mode setup
 */
function renderPracticeWeeksCheckboxGrid() {
  const grid = document.getElementById('practice-weeks-checkbox-grid');
  if (!grid) return;

  grid.innerHTML = '';

  const weeks = (appState.allWeeks && appState.allWeeks.length > 0)
    ? appState.allWeeks
    : Array.from({ length: 12 }, (_, i) => ({ week_number: i + 1, verified_questions: 10, title: `Week ${i + 1} Assignment` }));

  weeks.forEach(w => {
    const label = document.createElement('label');
    label.className = 'practice-week-checkbox-label';
    label.htmlFor = `practice-week-check-${w.week_number}`;

    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.id = `practice-week-check-${w.week_number}`;
    cb.value = String(w.week_number);
    cb.checked = practiceState.selectedWeeks.includes(w.week_number);

    if (cb.checked) label.classList.add('checked');

    cb.addEventListener('change', (e) => {
      const wNum = parseInt(e.target.value, 10);
      if (e.target.checked) {
        if (!practiceState.selectedWeeks.includes(wNum)) {
          practiceState.selectedWeeks.push(wNum);
          practiceState.selectedWeeks.sort((a, b) => a - b);
        }
        label.classList.add('checked');
      } else {
        practiceState.selectedWeeks = practiceState.selectedWeeks.filter(n => n !== wNum);
        label.classList.remove('checked');
      }
      updatePracticeConfigCalculations();
    });

    const infoDiv = document.createElement('div');
    infoDiv.className = 'checkbox-week-info';

    const numSpan = document.createElement('span');
    numSpan.className = 'checkbox-week-num';
    numSpan.textContent = `Week ${w.week_number}`;

    const subSpan = document.createElement('span');
    subSpan.className = 'checkbox-week-sub';
    subSpan.textContent = `${w.verified_questions || 10} verified questions`;

    infoDiv.appendChild(numSpan);
    infoDiv.appendChild(subSpan);

    label.appendChild(cb);
    label.appendChild(infoDiv);
    grid.appendChild(label);
  });

  updatePracticeConfigCalculations();
}

/**
 * Selects or deselects all weeks
 */
function selectAllPracticeWeeks(selectAll) {
  const grid = document.getElementById('practice-weeks-checkbox-grid');
  if (!grid) return;

  const checkboxes = grid.querySelectorAll('input[type="checkbox"]');
  practiceState.selectedWeeks = [];

  checkboxes.forEach(cb => {
    cb.checked = selectAll;
    const parentLabel = cb.closest('.practice-week-checkbox-label');
    if (selectAll) {
      practiceState.selectedWeeks.push(parseInt(cb.value, 10));
      if (parentLabel) parentLabel.classList.add('checked');
    } else {
      if (parentLabel) parentLabel.classList.remove('checked');
    }
  });

  practiceState.selectedWeeks.sort((a, b) => a - b);
  updatePracticeConfigCalculations();
}

/**
 * Recalculates available question counts and validates feasibility for test types
 */
function updatePracticeConfigCalculations() {
  const selectedCount = practiceState.selectedWeeks.length;
  const countBadge = document.getElementById('practice-selected-weeks-count');
  const completeHint = document.getElementById('complete-test-count-hint');
  const customMaxHint = document.getElementById('custom-max-hint');
  const customCountInput = document.getElementById('practice-custom-count');
  const quickContainer = document.getElementById('quick-counts-container');
  const quickNote = document.getElementById('quick-test-note');
  const weekError = document.getElementById('practice-week-error');

  if (countBadge) {
    countBadge.textContent = `${selectedCount} of 12 Weeks Selected`;
  }

  if (selectedCount === 0) {
    if (weekError) weekError.style.display = 'block';
  } else {
    if (weekError) weekError.style.display = 'none';
  }

  // Calculate available questions for selected weeks (10 per week)
  const totalAvailable = selectedCount * 10;

  if (completeHint) {
    completeHint.textContent = `${totalAvailable} Questions`;
  }

  if (customMaxHint) {
    customMaxHint.textContent = `Max: ${totalAvailable}`;
  }

  if (customCountInput) {
    customCountInput.max = String(totalAvailable);
    if (parseInt(customCountInput.value, 10) > totalAvailable && totalAvailable > 0) {
      customCountInput.value = String(totalAvailable);
      practiceState.customCount = totalAvailable;
    }
  }

  // Quick Test counts feasibility (10, 20, 30)
  if (quickContainer) {
    const pills = quickContainer.querySelectorAll('.btn-count-pill');
    let hasFeasibleQuickCount = false;

    pills.forEach(pill => {
      const cnt = parseInt(pill.getAttribute('data-count'), 10);
      if (cnt <= totalAvailable) {
        pill.disabled = false;
        hasFeasibleQuickCount = true;
      } else {
        pill.disabled = true;
        if (pill.classList.contains('active')) {
          pill.classList.remove('active');
        }
      }
    });

    // Ensure an active pill is chosen if possible
    if (hasFeasibleQuickCount) {
      const activePill = quickContainer.querySelector('.btn-count-pill.active:not(:disabled)');
      if (!activePill) {
        const firstEnabled = quickContainer.querySelector('.btn-count-pill:not(:disabled)');
        if (firstEnabled) {
          firstEnabled.classList.add('active');
          practiceState.quickCount = parseInt(firstEnabled.getAttribute('data-count'), 10);
        }
      }
      if (quickNote) quickNote.textContent = '';
    } else {
      if (quickNote) {
        quickNote.textContent = (selectedCount === 0)
          ? 'Please select at least 1 week to enable Quick Tests.'
          : 'Quick Tests require at least 10 available questions from selected weeks.';
      }
    }
  }
}

/**
 * Transitions into Practice Setup Card
 */
function showPracticeSetup() {
  const setupCard = document.getElementById('practice-setup-card');
  const testCard = document.getElementById('practice-test-card');
  const resultsCard = document.getElementById('practice-results-card');

  if (setupCard) setupCard.style.display = 'flex';
  if (testCard) testCard.style.display = 'none';
  if (resultsCard) resultsCard.style.display = 'none';

  practiceState.sessionId = null;
  practiceState.questions = [];
  practiceState.answers = {};
  practiceState.currentQuestionIndex = 0;

  updatePracticeConfigCalculations();
}

/**
 * Starts a new Practice Test session via backend API
 */
async function startPracticeTest() {
  const weekError = document.getElementById('practice-week-error');
  const typeError = document.getElementById('practice-type-error');
  const btnStart = document.getElementById('btn-start-practice-test');

  if (weekError) weekError.style.display = 'none';
  if (typeError) typeError.style.display = 'none';

  // 1. Validate week selection
  if (practiceState.selectedWeeks.length === 0) {
    if (weekError) {
      weekError.textContent = 'Please select at least one week to proceed.';
      weekError.style.display = 'block';
    }
    return;
  }

  // 2. Validate test type and question count
  const totalAvailable = practiceState.selectedWeeks.length * 10;
  let requestedCount = totalAvailable;

  if (practiceState.testType === 'quick') {
    if (practiceState.quickCount > totalAvailable) {
      if (typeError) {
        typeError.textContent = `Quick Test of ${practiceState.quickCount} questions cannot be created with only ${totalAvailable} available questions.`;
        typeError.style.display = 'block';
      }
      return;
    }
    requestedCount = practiceState.quickCount;
  } else if (practiceState.testType === 'custom') {
    const customInput = document.getElementById('practice-custom-count');
    const val = parseInt(customInput.value, 10);
    if (isNaN(val) || val <= 0) {
      if (typeError) {
        typeError.textContent = 'Please specify a positive question count.';
        typeError.style.display = 'block';
      }
      return;
    }
    if (val > totalAvailable) {
      if (typeError) {
        typeError.textContent = `Custom count (${val}) exceeds the ${totalAvailable} verified questions available in selected weeks.`;
        typeError.style.display = 'block';
      }
      return;
    }
    requestedCount = val;
    practiceState.customCount = val;
  }

  // 3. Dispatch session creation to backend
  if (btnStart) btnStart.disabled = true;

  try {
    const clientId = getGuestClientId();
    const payload = {
      weeks: practiceState.selectedWeeks,
      test_type: practiceState.testType,
      question_count: requestedCount,
      client_id: clientId
    };

    const response = await fetch(`${API_BASE}/api/practice/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-Client-ID': clientId
      },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.message || `Failed to create session (HTTP ${response.status})`);
    }

    const data = await response.json();
    const session = data.session;

    // Cache config for retake feature
    practiceState.lastConfig = {
      weeks: [...practiceState.selectedWeeks],
      test_type: practiceState.testType,
      question_count: requestedCount
    };

    // Save session in localStorage for reload recovery
    localStorage.setItem('nptel_active_session_id', session.id);

    // Load active session state
    practiceState.sessionId = session.id;
    practiceState.questions = session.questions || [];
    practiceState.answers = session.user_answers || {};
    practiceState.currentQuestionIndex = 0;

    // Hide resume banner
    const resumeBanner = document.getElementById('practice-resume-banner');
    if (resumeBanner) resumeBanner.style.display = 'none';

    // Transition to Active Test Card
    showActiveTest(session);

  } catch (err) {
    console.error('Error starting practice test:', err);
    if (typeError) {
      typeError.textContent = err.message || 'Failed to start practice test. Please try again.';
      typeError.style.display = 'block';
    }
  } finally {
    if (btnStart) btnStart.disabled = false;
  }
}

/**
 * Resumes an existing active practice session from backend
 */
async function resumePracticeSession(sessionId) {
  try {
    const clientId = getGuestClientId();
    const res = await fetch(`${API_BASE}/api/practice/sessions/${sessionId}`, {
      headers: {
        'Accept': 'application/json',
        'X-Client-ID': clientId
      }
    });

    if (res.status === 401 || res.status === 403) {
      alert('Cannot resume test: this session belongs to another client or identity could not be verified.');
      localStorage.removeItem('nptel_active_session_id');
      showPracticeSetup();
      return;
    }

    if (res.status === 404) {
      alert('Cannot resume test: practice session was not found.');
      localStorage.removeItem('nptel_active_session_id');
      showPracticeSetup();
      return;
    }

    if (!res.ok) {
      throw new Error(`Server returned HTTP ${res.status}`);
    }

    const data = await res.json();
    const session = data.session;

    if (!session) {
      localStorage.removeItem('nptel_active_session_id');
      showPracticeSetup();
      return;
    }

    // If session was already submitted, recover and render results
    if (session.status === 'submitted' || session.is_submitted === 1) {
      await recoverSubmittedResults(sessionId, clientId);
      return;
    }

    if (session.status !== 'active') {
      localStorage.removeItem('nptel_active_session_id');
      showPracticeSetup();
      return;
    }

    practiceState.sessionId = session.id;
    practiceState.selectedWeeks = session.selected_weeks || [];
    practiceState.testType = session.test_type;
    practiceState.questions = session.questions || [];
    practiceState.answers = session.user_answers || {};
    practiceState.currentQuestionIndex = 0;
    practiceState.lastConfig = {
      weeks: session.selected_weeks,
      test_type: session.test_type,
      question_count: session.total_questions
    };

    const resumeBanner = document.getElementById('practice-resume-banner');
    if (resumeBanner) resumeBanner.style.display = 'none';

    showActiveTest(session);

  } catch (err) {
    console.error('Failed to resume session:', err);
    // On network or 5xx error, DO NOT clear localStorage active session ID!
    alert('Unable to resume session due to a network or server error. Please check your connection and try again.');
    showPracticeSetup();
  }
}

/**
 * Recovers and renders results for a completed/submitted practice test
 */
async function recoverSubmittedResults(sessionId, clientId) {
  try {
    const resultsData = await fetchResultsWithRetry(sessionId, clientId);
    practiceState.cachedResults = resultsData;
    localStorage.removeItem('nptel_active_session_id');

    const resumeBanner = document.getElementById('practice-resume-banner');
    if (resumeBanner) resumeBanner.style.display = 'none';

    // Update Progress & Mastery
    const summary = resultsData.summary;
    const progress = getStoredProgress();

    (summary.selected_weeks || []).forEach(w => {
      if (!progress.practiced.includes(w)) {
        progress.practiced.push(w);
      }
    });

    if (summary.is_single_week && summary.is_mastered) {
      const wNum = summary.selected_weeks[0];
      if (!progress.mastered.includes(wNum)) {
        progress.mastered.push(wNum);
      }
    }

    saveStoredProgress(progress);
    renderPracticeResults(resultsData);
  } catch (err) {
    console.error('Error recovering submitted results:', err);
    alert('This test was completed, but results could not be downloaded: ' + err.message + '. Please click Resume Test again to retry.');
  }
}

/**
 * Transitions into Active Test Card and renders question navigator & first question
 */
function showActiveTest(session) {
  const setupCard = document.getElementById('practice-setup-card');
  const testCard = document.getElementById('practice-test-card');
  const resultsCard = document.getElementById('practice-results-card');

  if (setupCard) setupCard.style.display = 'none';
  if (resultsCard) resultsCard.style.display = 'none';
  if (testCard) testCard.style.display = 'flex';

  // Update header badges
  const typeBadge = document.getElementById('active-test-type-badge');
  const weeksBadge = document.getElementById('active-test-weeks-badge');

  if (typeBadge) {
    typeBadge.textContent = `${(session.test_type || 'practice').toUpperCase()} TEST`;
  }

  if (weeksBadge) {
    const weeksList = (session.selected_weeks || []).join(', ');
    weeksBadge.textContent = `Weeks: ${weeksList}`;
  }

  // Render Question Navigator
  renderPracticeNavigator();

  // Render current question
  renderPracticeActiveQuestion();

  window.scrollTo({ top: 120, behavior: 'smooth' });
}

/**
 * Renders the question navigator grid
 */
function renderPracticeNavigator() {
  const grid = document.getElementById('practice-navigator-grid');
  if (!grid || !practiceState.questions) return;

  grid.innerHTML = '';

  practiceState.questions.forEach((q, idx) => {
    const pill = document.createElement('button');
    pill.type = 'button';
    pill.className = 'nav-q-pill';
    pill.textContent = String(idx + 1);
    pill.setAttribute('aria-label', `Jump to question ${idx + 1}`);

    const isAnswered = practiceState.answers[q.id] !== undefined && practiceState.answers[q.id] !== null;
    const isCurrent = (idx === practiceState.currentQuestionIndex);

    if (isAnswered) pill.classList.add('answered');
    if (isCurrent) pill.classList.add('current');

    pill.addEventListener('click', () => {
      practiceState.currentQuestionIndex = idx;
      renderPracticeActiveQuestion();
    });

    grid.appendChild(pill);
  });
}

/**
 * Renders current question in Active Practice Test (without answer leakage)
 */
function renderPracticeActiveQuestion() {
  const qIndex = practiceState.currentQuestionIndex;
  const questions = practiceState.questions || [];
  if (questions.length === 0) return;

  const currentQ = questions[qIndex];
  const total = questions.length;

  // 1. Counter & Marks
  const counterElem = document.getElementById('active-question-counter');
  const marksElem = document.getElementById('active-question-marks');
  const questionTextElem = document.getElementById('active-practice-question-text');
  const optionsListElem = document.getElementById('active-practice-options-list');
  const btnPrev = document.getElementById('btn-practice-prev');
  const btnNext = document.getElementById('btn-practice-next');
  const btnClear = document.getElementById('btn-clear-answer');

  if (counterElem) counterElem.textContent = `Question ${qIndex + 1} of ${total}`;
  if (marksElem) {
    const marksVal = (currentQ.marks !== undefined && currentQ.marks !== null) ? Number(currentQ.marks).toFixed(1) : '1.0';
    marksElem.textContent = `${marksVal} Mark`;
  }
  if (questionTextElem) questionTextElem.textContent = currentQ.question_text || '';

  // 2. Prev / Next button states
  if (btnPrev) btnPrev.disabled = (qIndex === 0);
  if (btnNext) btnNext.disabled = (qIndex === total - 1);

  // 3. Selected Answer & Clear Button
  const selectedOptionId = practiceState.answers[currentQ.id];
  if (btnClear) {
    btnClear.style.display = (selectedOptionId !== undefined && selectedOptionId !== null) ? 'inline-block' : 'none';
  }

  // 4. Render Options (in preserved randomized order from session)
  if (optionsListElem) {
    optionsListElem.innerHTML = '';

    (currentQ.options || []).forEach(opt => {
      const isSelected = (selectedOptionId === opt.id);

      const optItem = document.createElement('div');
      optItem.className = isSelected ? 'practice-option-item selected' : 'practice-option-item';
      optItem.tabIndex = 0;
      optItem.setAttribute('role', 'radio');
      optItem.setAttribute('aria-checked', isSelected ? 'true' : 'false');

      const radioDot = document.createElement('span');
      radioDot.className = 'option-radio-dot';

      const optLeft = document.createElement('div');
      optLeft.className = 'option-left';

      const letterPill = document.createElement('span');
      letterPill.className = 'option-letter-pill';
      letterPill.textContent = (opt.option_letter || '').toUpperCase();

      const textSpan = document.createElement('span');
      textSpan.className = 'option-text';
      textSpan.textContent = opt.option_text || '';

      optLeft.appendChild(letterPill);
      optLeft.appendChild(textSpan);

      optItem.appendChild(radioDot);
      optItem.appendChild(optLeft);

      // Click to choose answer
      optItem.addEventListener('click', () => {
        selectPracticeOption(currentQ.id, opt.id);
      });

      optItem.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          selectPracticeOption(currentQ.id, opt.id);
        }
      });

      optionsListElem.appendChild(optItem);
    });
  }

  // 5. Update Navigator current indicator
  renderPracticeNavigator();
}

/* ==========================================================================
   Autosave Engine with Sequence Invariance & Bounded Retry
   ========================================================================== */

const autosaveState = {
  sequence: {},       // questionId -> latest sequence counter
  maxRetries: 2,
  timer: null
};

function setAutosaveBadge(status, text) {
  const badge = document.getElementById('practice-autosave-status');
  if (!badge) return;
  if (autosaveState.timer) {
    clearTimeout(autosaveState.timer);
    autosaveState.timer = null;
  }

  if (status === 'saving') {
    badge.className = 'autosave-status-badge saving';
    badge.textContent = text || 'Saving...';
    badge.style.display = 'inline-flex';
  } else if (status === 'saved') {
    badge.className = 'autosave-status-badge saved';
    badge.textContent = text || 'Saved ✓';
    badge.style.display = 'inline-flex';
    autosaveState.timer = setTimeout(() => {
      if (badge.classList.contains('saved')) {
        badge.style.display = 'none';
      }
    }, 2500);
  } else if (status === 'error') {
    badge.className = 'autosave-status-badge error';
    badge.textContent = text || 'Autosave failed';
    badge.style.display = 'inline-flex';
  } else {
    badge.style.display = 'none';
  }
}

async function dispatchAutosave(questionId, optionId, seq, attempt = 1) {
  // Stale check: if a newer selection occurred for this question, drop this request
  if (autosaveState.sequence[questionId] !== seq) {
    return;
  }

  if (!practiceState.sessionId) return;

  try {
    const clientId = getGuestClientId();
    const response = await fetch(`${API_BASE}/api/practice/sessions/${practiceState.sessionId}/answers`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-Client-ID': clientId
      },
      body: JSON.stringify({ answers: { [questionId]: optionId } })
    });

    // Check again if user changed selection while request was in-flight
    if (autosaveState.sequence[questionId] !== seq) {
      return;
    }

    if (response.ok) {
      setAutosaveBadge('saved', 'Saved ✓');
      return;
    }

    if (response.status === 403) {
      setAutosaveBadge('error', 'Test already submitted');
      return;
    }

    throw new Error(`HTTP ${response.status}`);
  } catch (err) {
    // If newer selection occurred, abort retry
    if (autosaveState.sequence[questionId] !== seq) {
      return;
    }

    if (attempt <= autosaveState.maxRetries) {
      setAutosaveBadge('saving', `Retrying save (${attempt}/${autosaveState.maxRetries})...`);
      setTimeout(() => {
        dispatchAutosave(questionId, optionId, seq, attempt + 1);
      }, attempt * 1000);
    } else {
      setAutosaveBadge('error', 'Autosave failed — offline');
      console.warn(`Autosave failed after ${autosaveState.maxRetries} retries for question ${questionId}:`, err);
    }
  }
}

/**
 * Records option selection and autosaves immediately to backend with sequence check
 */
async function selectPracticeOption(questionId, optionId) {
  autosaveState.sequence[questionId] = (autosaveState.sequence[questionId] || 0) + 1;
  const currentSeq = autosaveState.sequence[questionId];

  practiceState.answers[questionId] = optionId;
  renderPracticeActiveQuestion();
  setAutosaveBadge('saving', 'Saving...');

  if (practiceState.sessionId) {
    dispatchAutosave(questionId, optionId, currentSeq);
  }
}

/**
 * Clears selected answer for the current question
 */
async function clearCurrentPracticeAnswer() {
  const qIndex = practiceState.currentQuestionIndex;
  const questions = practiceState.questions || [];
  if (questions.length === 0) return;

  const currentQ = questions[qIndex];
  autosaveState.sequence[currentQ.id] = (autosaveState.sequence[currentQ.id] || 0) + 1;
  const currentSeq = autosaveState.sequence[currentQ.id];

  delete practiceState.answers[currentQ.id];
  renderPracticeActiveQuestion();
  setAutosaveBadge('saving', 'Saving...');

  if (practiceState.sessionId) {
    dispatchAutosave(currentQ.id, null, currentSeq);
  }
}

/**
 * Navigates between questions
 */
function navigatePracticeQuestion(direction) {
  const newIndex = practiceState.currentQuestionIndex + direction;
  if (newIndex >= 0 && newIndex < practiceState.questions.length) {
    practiceState.currentQuestionIndex = newIndex;
    renderPracticeActiveQuestion();
    window.scrollTo({ top: 120, behavior: 'smooth' });
  }
}

/**
 * Opens Submit Confirmation Modal
 */
function openSubmitConfirmModal() {
  const modal = document.getElementById('practice-confirm-modal');
  const warning = document.getElementById('modal-unanswered-warning');
  const unansweredCountElem = document.getElementById('modal-unanswered-count');
  if (!modal) return;

  const total = practiceState.questions.length;
  let answeredCount = 0;
  practiceState.questions.forEach(q => {
    if (practiceState.answers[q.id] !== undefined && practiceState.answers[q.id] !== null) {
      answeredCount++;
    }
  });

  const unanswered = total - answeredCount;

  if (unanswered > 0) {
    if (warning) warning.style.display = 'block';
    if (unansweredCountElem) unansweredCountElem.textContent = String(unanswered);
  } else {
    if (warning) warning.style.display = 'none';
  }

  modal.style.display = 'flex';
}

function closeSubmitConfirmModal() {
  const modal = document.getElementById('practice-confirm-modal');
  if (modal) modal.style.display = 'none';
}

/**
 * Helper to fetch results with bounded retry on network error
 */
async function fetchResultsWithRetry(sessionId, clientId, maxAttempts = 3) {
  let lastErr = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      const res = await fetch(`${API_BASE}/api/practice/sessions/${sessionId}/results`, {
        headers: {
          'Accept': 'application/json',
          'X-Client-ID': clientId
        }
      });
      if (res.ok) {
        return await res.json();
      }
      if (res.status === 401 || res.status === 403 || res.status === 404) {
        const errJson = await res.json().catch(() => ({}));
        throw new Error(errJson.message || `HTTP ${res.status}`);
      }
      lastErr = new Error(`HTTP ${res.status}`);
    } catch (err) {
      lastErr = err;
    }
    if (attempt < maxAttempts) {
      await new Promise(r => setTimeout(r, attempt * 1000));
    }
  }
  throw lastErr || new Error('Failed to retrieve test results after retries');
}

/**
 * Submits the test to server for grading and handles results recovery
 */
async function submitPracticeTest() {
  closeSubmitConfirmModal();

  if (!practiceState.sessionId) return;

  const btnSubmit = document.getElementById('btn-practice-submit');
  if (btnSubmit) {
    btnSubmit.disabled = true;
    btnSubmit.textContent = 'Submitting...';
  }

  let submittedSuccessfully = false;
  const clientId = getGuestClientId();
  const sessionId = practiceState.sessionId;

  try {
    const res = await fetch(`${API_BASE}/api/practice/sessions/${sessionId}/submit`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-Client-ID': clientId
      },
      body: JSON.stringify({ final_answers: practiceState.answers })
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.message || `Submission failed with HTTP ${res.status}`);
    }

    submittedSuccessfully = true;

    // Retrieve detailed results and review with bounded retry
    const resultsData = await fetchResultsWithRetry(sessionId, clientId);
    practiceState.cachedResults = resultsData;

    // Clear active session from localStorage
    localStorage.removeItem('nptel_active_session_id');

    // Update Progress & Mastery
    const summary = resultsData.summary;
    const progress = getStoredProgress();

    // Mark selected weeks as Practiced
    (summary.selected_weeks || []).forEach(w => {
      if (!progress.practiced.includes(w)) {
        progress.practiced.push(w);
      }
    });

    // Mastery Rule: Only single-week tests scoring >= 75% grant mastery
    if (summary.is_single_week && summary.is_mastered) {
      const wNum = summary.selected_weeks[0];
      if (!progress.mastered.includes(wNum)) {
        progress.mastered.push(wNum);
      }
    }

    saveStoredProgress(progress);

    // Transition to Results Card
    renderPracticeResults(resultsData);

  } catch (err) {
    console.error('Error during test submission/results:', err);
    if (submittedSuccessfully) {
      // The test WAS recorded and graded by the server, but results retrieval failed
      alert('Your test was submitted and graded successfully on the server, but the results could not be loaded due to a network error. Click "View Results" to retry loading.');
      if (btnSubmit) {
        btnSubmit.disabled = false;
        btnSubmit.textContent = 'View Results';
        btnSubmit.onclick = () => recoverSubmittedResults(sessionId, clientId);
      }
    } else {
      alert('Failed to submit test: ' + err.message + '. Please check your connection and try again.');
      if (btnSubmit) {
        btnSubmit.disabled = false;
        btnSubmit.textContent = 'Submit Test';
      }
    }
  } finally {
    if (!submittedSuccessfully && btnSubmit) {
      btnSubmit.disabled = false;
      btnSubmit.textContent = 'Submit Test';
    }
  }
}

/**
 * Renders Results and Answer Review Card
 */
function renderPracticeResults(resultsData) {
  const setupCard = document.getElementById('practice-setup-card');
  const testCard = document.getElementById('practice-test-card');
  const resultsCard = document.getElementById('practice-results-card');

  if (setupCard) setupCard.style.display = 'none';
  if (testCard) testCard.style.display = 'none';
  if (resultsCard) resultsCard.style.display = 'flex';

  const summary = resultsData.summary;

  // 1. Score and breakdown
  const scoreVal = document.getElementById('results-score-value');
  const totalMarks = document.getElementById('results-total-marks');
  const percentageBadge = document.getElementById('results-percentage-badge');
  const correctCount = document.getElementById('results-correct-count');
  const incorrectCount = document.getElementById('results-incorrect-count');
  const unansweredCount = document.getElementById('results-unanswered-count');

  if (scoreVal) scoreVal.textContent = Number(summary.score_earned).toFixed(1);
  if (totalMarks) totalMarks.textContent = `/ ${Number(summary.total_marks).toFixed(1)}`;
  if (percentageBadge) percentageBadge.textContent = `${Number(summary.percentage).toFixed(1)}%`;

  if (correctCount) correctCount.textContent = String(summary.correct_count);
  if (incorrectCount) incorrectCount.textContent = String(summary.incorrect_count);
  if (unansweredCount) unansweredCount.textContent = String(summary.unanswered_count);

  // 2. Mastery Banner
  const masteryBanner = document.getElementById('results-mastery-banner');
  if (masteryBanner) {
    masteryBanner.innerHTML = '';
    if (summary.is_single_week) {
      const weekNum = summary.selected_weeks[0];
      if (summary.is_mastered) {
        masteryBanner.className = 'mastery-banner earned';
        masteryBanner.innerHTML = `
          <span class="mastery-banner-icon">🏆</span>
          <div>
            <div class="mastery-banner-title">Week ${weekNum} Mastered!</div>
            <div class="mastery-banner-text">Outstanding! You achieved ${Number(summary.percentage).toFixed(1)}% (≥ 75%) in a single-week test. This assignment is now marked Mastered.</div>
          </div>
        `;
      } else {
        masteryBanner.className = 'mastery-banner info';
        masteryBanner.innerHTML = `
          <span class="mastery-banner-icon">🎯</span>
          <div>
            <div class="mastery-banner-title">Single-Week Test Completed</div>
            <div class="mastery-banner-text">You scored ${Number(summary.percentage).toFixed(1)}%. Week mastery requires scoring 75% or higher on a single-week practice test. Retake to earn mastery!</div>
          </div>
        `;
      }
    } else {
      masteryBanner.className = 'mastery-banner info';
      masteryBanner.innerHTML = `
        <span class="mastery-banner-icon">ℹ️</span>
        <div>
          <div class="mastery-banner-title">Mixed-Week Practice Test Completed</div>
          <div class="mastery-banner-text">All selected weeks (${(summary.selected_weeks || []).join(', ')}) have been marked Practiced. (Note: Per course rules, mixed-week tests do not alter single-week Mastery status).</div>
        </div>
      `;
    }
  }

  // 3. Question-by-Question Review
  const reviewList = document.getElementById('review-questions-list');
  if (reviewList) {
    reviewList.innerHTML = '';

    (resultsData.questions || []).forEach(q => {
      const card = document.createElement('div');
      card.className = 'review-question-card';

      // Header
      const head = document.createElement('div');
      head.className = 'review-q-header';

      const qNumSpan = document.createElement('span');
      qNumSpan.className = 'review-q-num';
      qNumSpan.textContent = `Question ${q.test_question_number} (Week ${q.week_number})`;

      const statusPill = document.createElement('span');
      if (q.is_correct) {
        statusPill.className = 'review-status-pill correct';
        statusPill.textContent = '✓ Correct (+1.0)';
      } else if (q.user_selected_option_id === null) {
        statusPill.className = 'review-status-pill unanswered';
        statusPill.textContent = '○ Unanswered (0.0)';
      } else {
        statusPill.className = 'review-status-pill incorrect';
        statusPill.textContent = '✗ Incorrect (0.0)';
      }

      head.appendChild(qNumSpan);
      head.appendChild(statusPill);
      card.appendChild(head);

      // Question text
      const p = document.createElement('p');
      p.className = 'question-text';
      p.textContent = q.question_text || '';
      card.appendChild(p);

      // Options review
      const optList = document.createElement('div');
      optList.className = 'review-options-list';

      (q.options || []).forEach(opt => {
        const isUserChoice = (q.user_selected_option_id === opt.id);
        const isCorrectChoice = opt.is_correct;

        const optRow = document.createElement('div');
        optRow.className = 'review-option';

        if (isCorrectChoice) {
          optRow.classList.add('correct-choice');
        } else if (isUserChoice && !isCorrectChoice) {
          optRow.classList.add('user-wrong');
        }

        const leftDiv = document.createElement('div');
        leftDiv.className = 'review-option-left';

        const letterPill = document.createElement('span');
        letterPill.className = isCorrectChoice ? 'option-letter-pill option-letter-correct' : 'option-letter-pill';
        letterPill.textContent = (opt.option_letter || '').toUpperCase();

        const optText = document.createElement('span');
        optText.className = 'option-text';
        optText.textContent = opt.option_text || '';

        leftDiv.appendChild(letterPill);
        leftDiv.appendChild(optText);
        optRow.appendChild(leftDiv);

        // Status badge on option
        if (isUserChoice && isCorrectChoice) {
          const badge = document.createElement('span');
          badge.className = 'review-option-badge correct';
          badge.textContent = '✓ Your Answer & Correct';
          optRow.appendChild(badge);
        } else if (isUserChoice && !isCorrectChoice) {
          const badge = document.createElement('span');
          badge.className = 'review-option-badge wrong';
          badge.textContent = '✗ Your Answer';
          optRow.appendChild(badge);
        } else if (isCorrectChoice) {
          const badge = document.createElement('span');
          badge.className = 'review-option-badge correct';
          badge.textContent = '✓ Correct Answer';
          optRow.appendChild(badge);
        }

        optList.appendChild(optRow);
      });

      card.appendChild(optList);
      reviewList.appendChild(card);
    });
  }

  window.scrollTo({ top: 120, behavior: 'smooth' });
}

/**
 * Retakes the test by creating a new independent attempt with identical parameters
 */
async function retakePracticeTest() {
  if (!practiceState.lastConfig) {
    showPracticeSetup();
    return;
  }

  const btnRetake = document.getElementById('btn-retake-test');
  if (btnRetake) btnRetake.disabled = true;

  try {
    const clientId = getGuestClientId();
    const payload = {
      weeks: practiceState.lastConfig.weeks,
      test_type: practiceState.lastConfig.test_type,
      question_count: practiceState.lastConfig.question_count,
      client_id: clientId
    };

    const res = await fetch(`${API_BASE}/api/practice/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-Client-ID': clientId
      },
      body: JSON.stringify(payload)
    });

    if (!res.ok) throw new Error('Failed to create retake session');

    const data = await res.json();
    const session = data.session;

    localStorage.setItem('nptel_active_session_id', session.id);

    practiceState.sessionId = session.id;
    practiceState.questions = session.questions || [];
    practiceState.answers = {};
    practiceState.currentQuestionIndex = 0;

    showActiveTest(session);

  } catch (err) {
    console.error('Error retaking test:', err);
    alert('Failed to retake test: ' + err.message);
  } finally {
    if (btnRetake) btnRetake.disabled = false;
  }
}
