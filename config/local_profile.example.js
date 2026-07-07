// Personal dashboard overrides — copy this file to config/local_profile.js
// (which is git-ignored) and put YOUR real numbers there. dashboard.html
// loads local_profile.js if it exists; otherwise it uses generic starter
// values. Never put real numbers in dashboard.html itself — it's tracked.
//
// Keep this roughly in sync with config/budget.json and config/profile.json
// (the Python scripts read those; the dashboard reads this).
window.LOCAL_BUDGET = {
  active_plan: "Current Plan",
  monthly_income_estimate: 3000,
  monthly_savings_goal: 500,
  category_budgets: {
    Groceries: 300, "Dining & Food": 200, "Gas & Fuel": 150,
    Shopping: 100, Entertainment: 50
  },
  // The categories your daily/weekly "safe to spend" number is computed from.
  discretionary_categories: ["Dining & Food", "Shopping", "Entertainment"],
  // Optional what-if plans, selectable in the dashboard's plan picker.
  alt_plans: {
    // "After the move": { monthly_income_estimate: 3500, monthly_savings_goal: 800 }
  }
};
window.LOCAL_PROFILE = {
  investments: { "Example Roth IRA": 1000.00 },
  loans: [{ name: "Example Student Loan", balance: 3000, rate: 5.5 }],
  goals: [{ name: "Emergency fund (3-6 mo)", current: 500, target: 3000 }]
};
// Optional: personal keyword->category rules, checked before the built-ins.
// Mirror config/rules.json here so the dashboard categorizes the same way.
// window.LOCAL_RULES = [
//   { category: "Groceries", keywords: ["my local market"] }
// ];
// Optional: one-off corrections, mirroring config/overrides.json.
// window.LOCAL_OVERRIDES = [
//   { description: "withdrawal", amount: -5000, category: "Auto & Vehicle", kind: "spend" }
// ];
