class FormCustomizer {
    constructor() {
        this.translations = {};
        if (this.isSharedForm()) {
            this.loadDatabaseStylesAndApply();
            return;
        }
        
        document.body.classList.add('has-customizer');
        
        this.settings = {};
        this.init();
    }
    applyStoredSettingsToForm() {
        Object.entries(this.settings).forEach(([key, value]) => {
            this.applyCustomization(key, value);
        });
    }

    isSharedForm() {
        return window.location.pathname.includes('/form_builder/shared/');
    }   

    async init() {
        this.translations = await getFormCustomizerTranslations();

        await this.loadDatabaseStylesAndApply();
        this.createCustomizationPanel();
        this.bindEvents();

            setTimeout(() => {
                this.updateUIControls();
            }, 200);
    }

    async loadDatabaseStylesAndApply() {
        const formId = this.getFormIdFromUrl();
        if (!formId) return;
        
        try {
            const url = `/form_builder/get_styles/${formId}`;
            
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                }
            });
            
            if (response.ok) {
                const data = await response.json();
                if (data.success) {
                    const databaseStyles = data.styles || {};
                    
                    this.settings = this.isSharedForm() 
                        ? databaseStyles 
                        : { ...databaseStyles, ...this.loadLocalSettings() };
                    
                    this.applyStoredSettingsToForm();
                    
                    if (!this.isSharedForm()) {
                        setTimeout(() => {
                            this.updateUIControls();
                        }, 100);

                    }
                    
                } else {
                    const failedLoadStyles = _t('Failed to load styles');
                    throw new Error(data.error || failedLoadStyles);
                }
            } else {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
        } catch (error) {
            if (!this.isSharedForm()) {
                this.settings = this.loadLocalSettings();
                this.applyStoredSettingsToForm();
                if (!this.isSharedForm()) {
                    setTimeout(() => {
                        this.updateUIControls();
                    }, 100);
                }
            }
        }
    }
loadLocalSettings() {
    const formId = this.getFormIdFromUrl();
    const storageKey = formId ? `form_customizer_settings_${formId}` : 'form_customizer_settings';
    
    const saved = localStorage.getItem(storageKey);
    return saved ? JSON.parse(saved) : {};
}

updateUIControls() {
    Object.entries(this.settings).forEach(([key, value]) => {
        const element = document.getElementById(key);
        if (element) {
            if (element.type === 'color' || element.type === 'text') {
                element.value = value;
            } else if (element.type === 'range') {
                element.value = value.replace('px', '');
                const valueSpan = element.nextElementSibling;
                if (valueSpan) valueSpan.textContent = value;
            } else {
                element.value = value;
            }
        }
    });
    }

    createCustomizationPanel() {
        const leftPanel = document.createElement('div');
        leftPanel.id = 'customization-panel';
        leftPanel.className = 'customization-panel';
        leftPanel.innerHTML = this.getCustomizationHTML();

        document.body.insertBefore(leftPanel, document.body.firstChild);

    }

    getCustomizationHTML() {
        const t = this.translations;
        
        return `
            <div class="customizer-header">
                <h5><i class="fa fa-palette"></i> ${t.formCustomizer}</h5>
            </div>
            
            <div class="customizer-content">
                <!-- Background Settings -->
                <div class="customizer-section">
                    <h6><i class="fa fa-image"></i> ${t.background}</h6>
                    <div class="setting-group">
                        <label>${t.pageBackground}</label>
                        <div class="color-input-group">
                            <input type="color" id="page-bg-color" value="#f8f9fa">
                            <input type="text" id="page-bg-text" value="#f8f9fa" class="color-text">
                        </div>
                    </div>
                    <div class="setting-group">
                        <label>${t.formContainerBackground}</label>
                        <div class="color-input-group">
                            <input type="color" id="form-bg-color" value="#ffffff">
                            <input type="text" id="form-bg-text" value="#ffffff" class="color-text">
                        </div>
                    </div>
                    <div class="setting-group">
                        <label>${t.formShadow}</label>
                        <div class="color-input-group">
                            <input type="color" id="form-shadow-color" value="#ffffff">
                            <input type="text" id="form-shadow-text" value="#ffffff" class="color-text">
                        </div>
                    </div>
                </div>

                <!-- Typography Settings -->
                <div class="customizer-section">
                    <h6><i class="fa fa-font"></i> ${t.typography}</h6>
                    <div class="setting-group">
                        <label>${t.formFontFamily}</label>
                        <select id="font-family">
                            <option value="system-ui, -apple-system, sans-serif">${t.systemDefault}</option>
                            <option value="Arial, sans-serif">Arial</option>
                            <option value="'Times New Roman', serif">Times New Roman</option>
                            <option value="'Courier New', monospace">Courier New</option>
                            <option value="Georgia, serif">Georgia</option>
                            <option value="'Trebuchet MS', sans-serif">Trebuchet MS</option>
                        </select>
                    </div>
                    <div class="setting-group">
                        <label>${t.fontSize}</label>
                        <select id="font-size">
                            <option value="14px">${t.small} (14px)</option>
                            <option value="16px" selected>${t.medium} (16px)</option>
                            <option value="18px">${t.large} (18px)</option>
                            <option value="20px">${t.extraLarge} (20px)</option>
                        </select>
                    </div>
                </div>

                <!-- Field Settings -->
                <div class="customizer-section">
                    <h6><i class="fa fa-edit"></i> ${t.formFields}</h6>
                    <div class="setting-group">
                        <label>${t.inputBackground}</label>
                        <div class="color-input-group">
                            <input type="color" id="input-bg-color" value="#ffffff">
                            <input type="text" id="input-bg-text" value="#ffffff" class="color-text">
                        </div>
                    </div>
                    <div class="setting-group">
                        <label>${t.inputBorderColor}</label>
                        <div class="color-input-group">
                            <input type="color" id="input-border-color" value="#ced4da">
                            <input type="text" id="input-border-text" value="#ced4da" class="color-text">
                        </div>
                    </div>
                    <div class="setting-group">
                        <label>${t.inputBorderRadius}</label>
                        <input type="range" id="input-border-radius" min="0" max="20" value="4" class="range-slider">
                        <span class="range-value">4px</span>
                    </div>
                </div>

                <!-- Label Settings -->
                <div class="customizer-section">
                    <h6><i class="fa fa-tags"></i> ${t.labelsAndTitle}</h6>
                    <div class="setting-group">
                        <label>${t.labelColor}</label>
                        <div class="color-input-group">
                            <input type="color" id="label-color" value="#212529">
                            <input type="text" id="label-color-text" value="#212529" class="color-text">
                        </div>
                    </div>
                    <div class="setting-group">
                        <label>${t.titleColor}</label>
                        <div class="color-input-group">
                            <input type="color" id="title-color" value="#0d6efd">
                            <input type="text" id="title-color-text" value="#0d6efd" class="color-text">
                        </div>
                    </div>
                    <div class="setting-group">
                        <label>${t.labelWeight}</label>
                        <select id="label-weight">
                            <option value="400">${t.normal}</option>
                            <option value="500">${t.medium}</option>
                            <option value="600" selected>${t.semiBold}</option>
                            <option value="700">${t.bold}</option>
                        </select>
                    </div>
                </div>

                <!-- Button Settings -->
                <div class="customizer-section">
                    <h6><i class="fa fa-mouse-pointer"></i> ${t.buttons}</h6>
                    <div class="setting-group">
                        <label>${t.buttonColor}</label>
                        <div class="color-input-group">
                            <input type="color" id="button-bg-color" value="#0d6efd">
                            <input type="text" id="button-bg-text" value="#0d6efd" class="color-text">
                        </div>
                    </div>
                    <div class="setting-group">
                        <label>${t.buttonTextColor}</label>
                        <div class="color-input-group">
                            <input type="color" id="button-text-color" value="#0d6efd">
                            <input type="text" id="button-text-text" value="#0d6efd" class="color-text">
                        </div>
                    </div>
                    <div class="setting-group">
                        <label>${t.buttonBorderRadius}</label>
                        <input type="range" id="button-border-radius" min="0" max="25" value="6" class="range-slider">
                        <span class="range-value">6px</span>
                    </div>
                </div>

                <!-- Spacing Settings -->
                <div class="customizer-section">
                    <h6><i class="fa fa-arrows-alt"></i> ${t.spacing}</h6>
                    <div class="setting-group">
                        <label>${t.fieldSpacing}</label>
                        <input type="range" id="field-spacing" min="10" max="40" value="20" class="range-slider">
                        <span class="range-value">20px</span>
                    </div>
                    <div class="setting-group">
                        <label>${t.formPadding}</label>
                        <input type="range" id="form-padding" min="15" max="50" value="25" class="range-slider">
                        <span class="range-value">25px</span>
                    </div>
                </div>

                <!-- Actions -->
                <div class="customizer-actions">
                    <button id="reset-customizer" class="btn btn-outline-danger btn-sm">
                        <i class="fa fa-undo"></i> ${t.resetToDefault}
                    </button>
                    <button id="save-customizer" class="btn btn-primary btn-sm style-save-button">
                        <i class="fa fa-save"></i> ${t.saveChanges}
                    </button>
                </div>
            </div>
        `;
    }

    bindEvents() {        
        this.bindColorInputs();
        
        this.bindRangeSliders();
        
        this.bindCustomizationControls();
        
        document.getElementById('reset-customizer').addEventListener('click', this.resetToDefault.bind(this));
document.getElementById('save-customizer').addEventListener('click', async (e) => {
    e.preventDefault();
    
    this.saveSettings();

    const dbSaved = await this.saveToDatabase();
    
    if (!dbSaved) {
        console.error('Database save failed, but localStorage save succeeded');
    }
});
    }

    bindColorInputs() {
        const colorPairs = [
            ['page-bg-color', 'page-bg-text'],
            ['form-bg-color', 'form-bg-text'],
            ['input-bg-color', 'input-bg-text'],
            ['input-border-color', 'input-border-text'],
            ['label-color', 'label-color-text'],
            ['button-bg-color', 'button-bg-text'],
            ['title-color', 'title-color-text'],
            ['button-text-color', 'button-text-text'],
            ['form-shadow-color', 'form-shadow-text'],
        ];

        colorPairs.forEach(([colorId, textId]) => {
            const colorInput = document.getElementById(colorId);
            const textInput = document.getElementById(textId);

            colorInput.addEventListener('input', (e) => {
                textInput.value = e.target.value;
                this.applyCustomization(colorId, e.target.value);
            });

            textInput.addEventListener('input', (e) => {
                if (this.isValidColor(e.target.value)) {
                    colorInput.value = e.target.value;
                    this.applyCustomization(colorId, e.target.value);
                }
            });
        });
    }

    bindRangeSliders() {
        const sliders = ['input-border-radius', 'button-border-radius', 'field-spacing', 'form-padding'];
        
        sliders.forEach(sliderId => {
            const slider = document.getElementById(sliderId);
            const valueSpan = slider.nextElementSibling;
            
            slider.addEventListener('input', (e) => {
                valueSpan.textContent = e.target.value + 'px';
                this.applyCustomization(sliderId, e.target.value + 'px');
            });
        });
    }

    bindCustomizationControls() {
        const controls = [
            'font-family', 'font-size', 'label-weight'
        ];

        controls.forEach(controlId => {
            document.getElementById(controlId).addEventListener('change', (e) => {
                this.applyCustomization(controlId, e.target.value);
            });
        });
    }

    applyCustomization(settingId, value) {
        const formId = this.getFormIdFromUrl();
        if (!formId) {
            console.error('Form ID not found');
            return;
        }

        this.settings[settingId] = value;
        console.log(`Applied setting: ${settingId} = ${value}`);
        
        const formScope = `.form-id-${formId}`;
        const formWrapper = document.querySelector(`${formScope}.form-preview-wrapper`);
        const formCard = document.querySelector(`${formScope} .form-preview-card`);
        const formFields = document.querySelectorAll(`${formScope} .form-field`);
        const inputs = document.querySelectorAll(`${formScope} .form-control`);
        const labels = document.querySelectorAll(`${formScope} .form-label, ${formScope} .form-check-label`);
        const buttons = document.querySelectorAll(`${formScope} .form-submit-button`); 

        

        switch (settingId) {
            case 'page-bg-color':
                if (formWrapper) {
                    formWrapper.style.background = `linear-gradient(135deg, ${value}, ${this.adjustBrightness(value, 20)})`;
                }
                break;
            case 'form-bg-color':
                if (formCard) formCard.style.backgroundColor = value;
                break;
            case 'form-shadow-color':
                if (formCard) formCard.style.boxShadow = `2px 2px 16px 4px ${value}`;
                break;
            case 'font-family':
                if (formCard) formCard.style.fontFamily = value;
                break;
            case 'font-size':
                if (formCard) formCard.style.fontSize = value;
                break;
            case 'input-bg-color':
                inputs.forEach(input => input.style.backgroundColor = value);
                break;
            case 'input-border-color':
                inputs.forEach(input => input.style.borderColor = value);
                break;
            case 'input-border-radius':
                inputs.forEach(input => input.style.borderRadius = value);
                break;
            case 'label-color':
                labels.forEach(label => label.style.color = value);
                break;
            case 'label-weight':
                labels.forEach(label => label.style.fontWeight = value);
                break;
            case 'button-bg-color':
                buttons.forEach(button => {
                    button.style.setProperty('background-color', value, 'important');
                    button.style.setProperty('border-color', value, 'important');
                });
                
                const hoverStyleId = `custom-button-hover-${formId}`;
                let hoverStyle = document.getElementById(hoverStyleId);
                
                if (!hoverStyle) {
                    hoverStyle = document.createElement('style');
                    hoverStyle.id = hoverStyleId;
                    document.head.appendChild(hoverStyle);
                }
                
                const hoverColor = this.adjustBrightness(value, -10);
                hoverStyle.textContent = `
                    ${formScope} .form-submit-button:hover {
                        background-color: ${hoverColor} !important;
                        border-color: ${hoverColor} !important;
                    }
                    ${formScope} #form-submit-button:active {
                        background-color: ${this.adjustBrightness(value, -20)} !important;
                        border-color: ${this.adjustBrightness(value, -20)} !important;
                    }
                `;
                break;
            case 'button-text-color':
                buttons.forEach(button => {
                    button.style.setProperty('color', value, 'important');
                });
                break;
            case 'button-border-radius':
                buttons.forEach(button => button.style.borderRadius = value);
                break;
            case 'field-spacing':
                formFields.forEach(field => field.style.marginBottom = value);
                break;
            case 'form-padding':
                formCard.style.padding = value;
                break;
            case 'title-color':
                const title = document.querySelector(`${formScope} .form-header h2`);
                if (title) title.style.color = value;
                break;
        }

        this.settings[settingId] = value;
    }

    saveSettings() {
        const formId = this.getFormIdFromUrl();
        const storageKey = formId ? `form_customizer_settings_${formId}` : 'form_customizer_settings';
        
        localStorage.setItem(storageKey, JSON.stringify(this.settings));
        this.showNotification('settingsSavedSuccessfully', 'success');
    }
    loadSettings() {
        const formId = this.getFormIdFromUrl();
        const storageKey = formId ? `form_customizer_settings_${formId}` : 'form_customizer_settings';
        
        const saved = localStorage.getItem(storageKey);
        return saved ? JSON.parse(saved) : {};
    }

    resetToDefault() {
        this.settings = {};
        localStorage.removeItem('form_customizer_settings');
        location.reload();
    }

    showNotification(messageKey, type = 'info') {
        const message = this.translations[messageKey] || messageKey;
        const notification = document.createElement('div');
        notification.className = `alert alert-${type} customizer-notification`;
        notification.textContent = message;
        
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.classList.add('show');
        }, 100);
        
        setTimeout(() => {
            notification.remove();
        }, 3000);
    }

    adjustBrightness(color, amount) {
        const num = parseInt(color.replace("#", ""), 16);
        const amt = Math.round(2.55 * amount);
        const R = (num >> 16) + amt;
        const G = (num >> 8 & 0x00FF) + amt;
        const B = (num & 0x0000FF) + amt;
        return "#" + (0x1000000 + (R < 255 ? R < 1 ? 0 : R : 255) * 0x10000 +
            (G < 255 ? G < 1 ? 0 : G : 255) * 0x100 +
            (B < 255 ? B < 1 ? 0 : B : 255)).toString(16).slice(1);
    }

    isValidColor(color) {
        return /^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$/.test(color);
    }

async saveToDatabase() {
    const formId = this.getFormIdFromUrl();
    if (!formId) {
        this.showNotification('formIDNotFound', 'error');
        return false;
    }

    try {
        const requestBody = JSON.stringify({ styles: this.settings });
        
        const response = await fetch(`/form_builder/save_styles/${formId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
            body: requestBody
        });

        const result = await response.json();

        if (response.ok) {
            const actualResult = result.result || result;
            
            if (actualResult.success) {
                this.showNotification('stylesFileToDatabase', 'success');
                return true;
            } else {
                throw new Error(actualResult.error || 'Save failed');
            }
        } else {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
    } catch (error) {
        console.error('Error saving styles:', error);
        const errorMsg = `${this.translations.errorSavingStyles} ${error.message}`;
        this.showNotification(errorMsg, 'error');
        return false;
    }
}

    getFormIdFromUrl() {
        if (window.CURRENT_FORM_ID) {
            return window.CURRENT_FORM_ID.toString();
        }
        
        let match = window.location.pathname.match(/\/form_builder\/preview\/(\d+)/);
        if (match) return match[1];
        
        match = window.location.pathname.match(/\/form_builder\/shared\//);
        if (match && window.CURRENT_FORM_ID) {
            return window.CURRENT_FORM_ID.toString();
        }
        
        return null;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    new FormCustomizer();
});