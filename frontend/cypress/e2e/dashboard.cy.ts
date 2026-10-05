describe("LedgerSync dashboard", () => {
  it("logs in and shows the reconciliation workspace", () => {
    cy.visit("/");
    cy.get('input[autocomplete="username"]').clear().type("admin@example.com");
    cy.get('input[autocomplete="current-password"]').clear().type("Admin12345!");
    cy.contains("Sign in").click();
    cy.contains("Reconcile with confidence").should("be.visible");
    cy.contains("Upload source batch").should("be.visible");
  });
});
