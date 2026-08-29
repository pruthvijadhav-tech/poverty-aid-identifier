
const MH_KEYWORDS = [
  'maharashtra', 'pune', 'mumbai', 'nashik', 'nagpur', 'sambhaji nagar',
  'solapur', 'kolhapur', 'satara', 'sangli', 'ahmednagar', 'latur',
  'nanded', 'osmanabad', 'beed', 'jalna', 'hingoli', 'parbhani',
  'washim', 'akola', 'amravati', 'wardha', 'yavatmal', 'buldhana',
  'chandrapur', 'gadchiroli', 'gondia', 'bhandara', 'raigad',
  'ratnagiri', 'sindhudurg', 'thane', 'palghar', 'dhule', 'nandurbar',
  'jalgaon', 'hinganghat', 'vidarbha', 'marathwada', 'konkan', 'mh',
];

const SCHEMES_EN = {
  pm_jan_arogya:    ['urgent', 'PM Jan Arogya Yojana (Emergency Medical Aid)', 'Rs. 5,00,000/yr'],
  state_emergency:  ['urgent', 'State Emergency Relief Fund (Accident)', 'Rs. 10,000'],
  national_family:  ['urgent', 'National Family Benefit Scheme (Death of Earning Member)', 'Rs. 20,000'],
  pm_poshan:        ['normal', 'PM Poshan Scheme (Nutrition for Children)', 'Free Meals'],
  icds:             ['normal', 'Integrated Child Development Services (ICDS)', 'Free Services'],
  old_age_pension:  ['normal', 'Indira Gandhi National Old Age Pension', 'Rs. 200-500/month'],
  widow_pension:    ['urgent', 'Indira Gandhi National Widow Pension Scheme (IGNWPS)', 'Rs. 300-500/month'],
  annapurna:        ['normal', 'Annapurna Scheme (Free Food for Elderly)', '10 kg/month'],
  ayushman:         ['normal', 'Ayushman Bharat (Free Health Insurance)', 'Rs. 5,00,000/yr'],
  divyangjan:       ['normal', 'Divyangjan Swavalamban Scheme', 'Rs. 300-1500/month'],
  accessible_india: ['normal', 'Accessible India Campaign - Disability Aid', 'Free Aids/Equipment'],
  pm_awas:          ['normal', 'PM Awas Yojana (Free Housing)', 'Rs. 1,20,000'],
  antyodaya:        ['normal', 'Antyodaya Anna Yojana (Free Ration)', '35 kg/month'],
  ujjwala:          ['normal', 'PM Ujjwala Yojana (Free Gas Connection)', '1 Free Cylinder'],
  saubhagya:        ['normal', 'Saubhagya Scheme (Free Electricity)', 'Free Connection'],
  jan_dhan:         ['normal', 'PM Jan Dhan Yojana (Free Bank Account)', 'Zero Balance Account'],
  basic:            ['normal', 'Basic Community Support and Ration Assistance', 'As applicable'],
};

const MH_SCHEMES_EN = {
  ladki_bahin:   ['urgent', 'Ladki Bahin Yojana (Maharashtra)', 'Rs. 1,500/month'],
  mh_health:     ['urgent', 'Mahatma Phule Jan Arogya Yojana (MH)', 'Rs. 5 lakh/yr'],
  shravan_bal:   ['normal', 'Shravan Bal Seva Pension (MH)', 'Rs. 600/month'],
  gharkul:       ['normal', 'Ramai Awas Gharkul Yojana (MH)', 'Free House'],
  sanjay_gandhi: ['normal', 'Sanjay Gandhi Niradhar Yojana (MH)', 'Rs. 600/month'],
  rajmata_jijau: ['normal', 'Rajmata Jijau Mata-Bal Swasthya (MH)', 'Free maternal health'],
  mh_ration:     ['normal', 'Maharashtra Yellow Ration Card (MH)', 'Subsidised ration'],
  vayoshri_mh:   ['normal', 'Vayoshri Yojana Maharashtra (MH)', 'Free aids for elderly'],
};

function calculateScore(data) {
  let score = 0;
  const ageGroup = data.age_group;
  if (ageGroup === 'child') score += 30;
  else if (ageGroup === 'elderly') score += 25;

  const income = parseInt(data.income, 10) || 0;
  if (income < 5000) score += 40;
  else if (income < 10000) score += 25;
  else if (income < 20000) score += 10;

  const family = parseInt(data.family_size, 10) || 0;
  if (family >= 5) score += 20;
  else if (family >= 3) score += 10;

  if (data.housing === 'homeless') score += 20;
  else if (data.housing === 'kutcha') score += 15;
  else if (data.housing === 'rented') score += 5;

  if (data.electricity === 'no') score += 10;
  else if (data.electricity === 'sometimes') score += 5;

  if (data.ration === 'no') score += 10;

  if (data.medical === 'emergency') score += 30;
  else if (data.medical === 'chronic_illness') score += 15;
  else if (data.medical === 'disability') score += 20;

  if (data.accident === 'yes') score += 25;
  if (data.earning_member_died === 'yes') score += 25;
  if (data.widow_status === 'yes') score += 15;

  return score;
}

function getPriority(score, data) {
  const age = data.age_group;
  if (age === 'child' && score >= 40) return 'CRITICAL - Child in Need, Immediate Help Required';
  if (age === 'elderly' && score >= 40) return 'CRITICAL - Elderly Person, Immediate Help Required';
  if (data.medical === 'emergency' || data.accident === 'yes') return 'CRITICAL - Medical or Accident Emergency, Immediate Help';
  if (score >= 60) return 'HIGH NEED - Urgent Help Required';
  if (score >= 40) return 'MODERATE NEED - Eligible for Aid';
  if (score >= 20) return 'LOW NEED - Some Schemes Available';
  return 'Will Receive Basic Community Help';
}

function getSchemes(score, data) {
  const schemes = [];
  const age = data.age_group;
  const medical = data.medical;
  const accident = data.accident;
  const housing = data.housing;
  const electricity = data.electricity;
  const ration = data.ration;
  const earning = data.earning_member_died;
  const widowStatus = data.widow_status || 'no';
  const income = parseInt(data.income, 10) || 0;
  const address = (data.address || '').toLowerCase();

  const push = (key, table) => schemes.push([key, ...table[key]]);

  if (medical === 'emergency') push('pm_jan_arogya', SCHEMES_EN);
  if (accident === 'yes') push('state_emergency', SCHEMES_EN);
  if (earning === 'yes') push('national_family', SCHEMES_EN);
  if (widowStatus === 'yes') push('widow_pension', SCHEMES_EN);
  if (age === 'child') { push('pm_poshan', SCHEMES_EN); push('icds', SCHEMES_EN); }
  if (age === 'elderly') { push('old_age_pension', SCHEMES_EN); push('annapurna', SCHEMES_EN); }
  if (medical === 'chronic_illness') push('ayushman', SCHEMES_EN);
  if (medical === 'disability') { push('divyangjan', SCHEMES_EN); push('accessible_india', SCHEMES_EN); }
  if (housing === 'homeless' || housing === 'kutcha') push('pm_awas', SCHEMES_EN);
  if (ration === 'no') push('antyodaya', SCHEMES_EN);
  if (electricity === 'no') { push('ujjwala', SCHEMES_EN); push('saubhagya', SCHEMES_EN); }
  if (score >= 40) push('jan_dhan', SCHEMES_EN);
  push('basic', SCHEMES_EN);

  const isMH = MH_KEYWORDS.some((kw) => address.includes(kw));
  if (isMH) {
    if (income < 20834) push('ladki_bahin', MH_SCHEMES_EN);
    if (['emergency', 'chronic_illness', 'disability'].includes(medical) || income < 10000) push('mh_health', MH_SCHEMES_EN);
    if (age === 'elderly') {
      push('shravan_bal', MH_SCHEMES_EN);
      if (['disability', 'chronic_illness'].includes(medical)) push('vayoshri_mh', MH_SCHEMES_EN);
    }
    if (housing === 'homeless' || housing === 'kutcha') push('gharkul', MH_SCHEMES_EN);
    if (earning === 'yes' || widowStatus === 'yes' || (income < 5000 && age === 'elderly')) push('sanjay_gandhi', MH_SCHEMES_EN);
    if (age === 'child') push('rajmata_jijau', MH_SCHEMES_EN);
    if (ration === 'no' || income < 10000) push('mh_ration', MH_SCHEMES_EN);
  }

  const seen = new Set();
  return schemes.filter((item) => {
    if (seen.has(item[0])) return false;
    seen.add(item[0]);
    return true;
  });
}

function checkEligibilityOffline(data) {
  const score = calculateScore(data);
  const schemes = getSchemes(score, data);
  const priority = getPriority(score, data);
  return { score, priority, schemes };
}

if (typeof module !== 'undefined') {
  module.exports = { calculateScore, getSchemes, getPriority, checkEligibilityOffline };
}