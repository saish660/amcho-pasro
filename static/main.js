const mobileMenuToggle = document.getElementById("mobile-menu-toggle");
const mobileSidebar = document.getElementById("mobile-sidebar");
const sidebarClose = document.getElementById("sidebar-close");
const sidebarOverlay = document.getElementById("sidebar-overlay");
const sidebarLinks = document.querySelectorAll(".sidebar-link");

function openSidebar() {
  if (mobileSidebar) mobileSidebar.classList.add("active");
  if (sidebarOverlay) sidebarOverlay.classList.add("active");
  if (mobileMenuToggle) mobileMenuToggle.classList.add("active");
  document.body.style.overflow = "hidden";
}

function closeSidebar() {
  if (mobileSidebar) mobileSidebar.classList.remove("active");
  if (sidebarOverlay) sidebarOverlay.classList.remove("active");
  if (mobileMenuToggle) mobileMenuToggle.classList.remove("active");
  document.body.style.overflow = "";
}

if (mobileMenuToggle && mobileSidebar) {
  mobileMenuToggle.addEventListener("click", function () {
    if (mobileSidebar.classList.contains("active")) {
      closeSidebar();
    } else {
      openSidebar();
    }
  });
}

if (sidebarClose) sidebarClose.addEventListener("click", closeSidebar);
if (sidebarOverlay) sidebarOverlay.addEventListener("click", closeSidebar);

sidebarLinks.forEach((link) => {
  link.addEventListener("click", function () {
    closeSidebar();
  });
});

window.addEventListener("resize", function () {
  if (
    window.innerWidth > 768 &&
    mobileSidebar &&
    mobileSidebar.classList.contains("active")
  ) {
    closeSidebar();
  }
});

function isMobileDevice() {
  return window.innerWidth <= 768;
}

function isTabletDevice() {
  return window.innerWidth <= 1024 && window.innerWidth > 768;
}

// Authentication functionality
document.addEventListener("DOMContentLoaded", function () {
  // Password toggle functionality
  const passwordToggles = document.querySelectorAll(".password-toggle");

  passwordToggles.forEach((toggle) => {
    toggle.addEventListener("click", function () {
      const passwordField = this.parentElement.querySelector("input");
      const toggleText = this.querySelector(".password-toggle-text");

      if (passwordField.type === "password") {
        passwordField.type = "text";
        toggleText.textContent = "Hide";
      } else {
        passwordField.type = "password";
        toggleText.textContent = "Show";
      }
    });
  });

  // Login & signup forms now post directly to Flask backend.

  // Social login buttons (placeholder functionality)
  const socialButtons = document.querySelectorAll(".social-button");
  socialButtons.forEach((button) => {
    button.addEventListener("click", function () {
      const provider = this.classList.contains("google-btn")
        ? "Google"
        : "Facebook";
      alert(`${provider} authentication would be implemented here.`);
    });
  });

  function validateStep(stepEl) {
    if (!stepEl) return true;
    const controls = stepEl.querySelectorAll("input, select, textarea");
    for (const control of controls) {
      if (typeof control.reportValidity === "function") {
        if (!control.reportValidity()) {
          return false;
        }
      }
    }
    return true;
  }

  function initMultiStepForms() {
    const forms = document.querySelectorAll(".multi-step-form");
    forms.forEach((form) => {
      const steps = Array.from(form.querySelectorAll(".form-step"));
      if (steps.length <= 1) return;
      const progressSteps = Array.from(
        form.querySelectorAll(".form-progress__step")
      );
      const prevBtn = form.querySelector('[data-step-action="prev"]');
      const nextBtn = form.querySelector('[data-step-action="next"]');
      const submitBtn = form.querySelector(".form-submit");
      let activeIndex = 0;

      form.classList.add("multi-step-enabled");

      function setStep(newIndex) {
        if (newIndex < 0 || newIndex >= steps.length) return;
        steps.forEach((step, idx) => {
          const isActive = idx === newIndex;
          step.classList.toggle("is-active", isActive);
          step.setAttribute("aria-hidden", String(!isActive));
        });

        progressSteps.forEach((stepIndicator, idx) => {
          stepIndicator.classList.toggle("is-active", idx === newIndex);
          stepIndicator.classList.toggle("is-complete", idx < newIndex);
        });

        if (prevBtn) {
          prevBtn.disabled = newIndex === 0;
        }

        if (nextBtn) {
          nextBtn.hidden = newIndex === steps.length - 1;
        }

        if (submitBtn) {
          submitBtn.hidden = newIndex !== steps.length - 1;
        }

        activeIndex = newIndex;
        window.dispatchEvent(
          new CustomEvent("amcho:stepchange", {
            detail: {
              formId: form.id || null,
              stepIndex: activeIndex,
              stepNumber: activeIndex + 1,
            },
          })
        );
      }

      setStep(activeIndex);

      form.addEventListener("click", (event) => {
        const actionTrigger = event.target.closest("[data-step-action]");
        if (!actionTrigger) return;
        event.preventDefault();
        const action = actionTrigger.dataset.stepAction;
        if (action === "next") {
          const currentStep = steps[activeIndex];
          if (!validateStep(currentStep)) return;
          setStep(activeIndex + 1);
        } else if (action === "prev") {
          setStep(activeIndex - 1);
        }
      });

      form.addEventListener("submit", (event) => {
        if (activeIndex !== steps.length - 1) {
          event.preventDefault();
          const currentStep = steps[activeIndex];
          if (!validateStep(currentStep)) return;
          setStep(activeIndex + 1);
        }
      });
    });
  }

  initMultiStepForms();
});
