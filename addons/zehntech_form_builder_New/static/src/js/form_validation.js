console.log('form validation loaded');

window.handleFileUpload = function(input) {
    const showPreview = input.getAttribute('data-show-preview') === 'true';
    const allowMultiple = input.getAttribute('data-multiple') === 'true';
    
    if (allowMultiple && input.hasAttribute('data-file-count')) {
        const currentFileCount = parseInt(input.getAttribute('data-file-count'));
        
        const existingFiles = [];
        if (window.fileStorage && window.fileStorage[input.id]) {
            existingFiles.push(...window.fileStorage[input.id]);
        }
        
        const newFiles = Array.from(input.files);
        const combinedFiles = [...existingFiles, ...newFiles];
        
        const dt = new DataTransfer();
        combinedFiles.forEach(file => {
            if (file instanceof File) {
                dt.items.add(file);
            }
        });
        
        input.files = dt.files;
        
        if (!window.fileStorage) window.fileStorage = {};
        window.fileStorage[input.id] = Array.from(input.files);
        input.setAttribute('data-file-count', input.files.length);
        
    } else if (allowMultiple && input.files.length > 0) {
        if (!window.fileStorage) window.fileStorage = {};
        window.fileStorage[input.id] = Array.from(input.files);
        input.setAttribute('data-file-count', input.files.length);
    }
    
    if (showPreview && input.files.length > 0) {
        showFilePreview(input, input.files);
    }
    
    if (allowMultiple && input.files.length > 0) {
        input.style.display = 'none';
        
        const addMoreBtn = document.getElementById('add_more_' + input.id.replace('file_', ''));
        if (addMoreBtn) {
            addMoreBtn.style.display = 'inline-block';
        }
    }
    
    if (typeof validateField === 'function') {
        validateField(input);
    }
}

window.triggerFileInput = function(inputId) {
    const input = document.getElementById(inputId);
    if (input) {
        input.style.display = 'block';
        input.click();
        
        setTimeout(() => {
            input.style.display = 'none';
        }, 100);
    }
}

window.showFilePreview = function(field, files) {
    const previewDiv = document.getElementById(field.id.replace('file_', 'preview_'));
    if (!previewDiv) return;
    
    previewDiv.innerHTML = '';
    
    const fileArray = Array.from(files);
    
    fileArray.forEach((file, index) => {
        const preview = document.createElement('div');
        preview.className = 'file-preview-item d-flex align-items-center justify-content-between p-2 mb-2 border rounded';
        preview.style.backgroundColor = '#f8f9fa';
        preview.style.display = 'flex';
        preview.style.alignItems = 'center';
        preview.style.justifyContent = 'space-between';
        preview.style.padding = '7px';

        
        const fileInfo = document.createElement('div');
        fileInfo.className = 'd-flex align-items-center';
        fileInfo.style.display = 'flex';
        fileInfo.style.alignItems = 'top';
        fileInfo.style.gap = '10px';

        fileInfo.innerHTML = `
            <i class="fas fa-file me-2" style="color: #6c757d; margin-top:5px;"></i>
            <div>
                <div style="font-weight: 500;">${file.name}</div>
                <small style="color: #6c757d;">${(file.size / 1024).toFixed(2)} KB</small>
            </div>
        `;
        
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn btn-sm btn-danger';
        removeBtn.innerHTML = '<i class="fa fa-times"></i>';
        removeBtn.onclick = function() {
            removeFile(field, index);
        };
        
        preview.appendChild(fileInfo);
        preview.appendChild(removeBtn);
        previewDiv.appendChild(preview);
    });
}

window.removeFile = function(input, indexToRemove) {
    const allowMultiple = input.getAttribute('data-multiple') === 'true';
    const dt = new DataTransfer();
    const files = input.files;
    
    for (let i = 0; i < files.length; i++) {
        if (i !== indexToRemove) {
            dt.items.add(files[i]);
        }
    }
    
    input.files = dt.files;
    
    if (allowMultiple && window.fileStorage) {
        window.fileStorage[input.id] = Array.from(input.files);
        input.setAttribute('data-file-count', input.files.length);
    }
    
    if (input.files.length > 0) {
        showFilePreview(input, input.files);
    } else {
        const previewDiv = document.getElementById(input.id.replace('file_', 'preview_'));
        if (previewDiv) {
            previewDiv.innerHTML = '';
        }
        
        if (allowMultiple) {
            input.style.display = 'block';
            const addMoreBtn = document.getElementById('add_more_' + input.id.replace('file_', ''));
            if (addMoreBtn) {
                addMoreBtn.style.display = 'none';
            }
            if (window.fileStorage) {
                delete window.fileStorage[input.id];
            }
            input.removeAttribute('data-file-count');
        }
    }
    
    validateField(input);
}

document.addEventListener('DOMContentLoaded', function() {
    document.querySelector('form').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            const emptyNonRequiredFields = Array.from(this.querySelectorAll('.validation-field:not([required])')).filter(field => !field.value.trim());

            if (emptyNonRequiredFields.length > 0) {
                e.preventDefault();
                return false;
            }

            const requiredFields = Array.from(this.querySelectorAll('.validation-field[required]'));
            const allRequiredFilled = requiredFields.every(field => validateField(field));

            if (!allRequiredFilled) {
                e.preventDefault();
                return false;
            }
        }
    });

    
    document.querySelectorAll('.validation-field').forEach(function(field) {
        field.addEventListener('input', function() {
            validateField(this);
        });

        field.addEventListener('change', function() {  
            validateField(this);
        });

        
        field.addEventListener('blur', function() {
            validateField(this);
        });
        
    });

    // ! Password toggle functionality.
        document.querySelectorAll('.password-toggle').forEach(button => {
            button.addEventListener('click', function() {
                const targetId = this.getAttribute('data-target');
                const input = document.getElementById(targetId);
                const icon = this.querySelector('i');
            
                if (input.type === 'password') {
                    input.type = 'text';
                    icon.classList.remove('fa-eye');
                    icon.classList.add('fa-eye-slash');
                } else {
                    input.type = 'password';
                    icon.classList.remove('fa-eye-slash');
                    icon.classList.add('fa-eye');
                }
            
                validateField(input);
            });
        });

        document.querySelectorAll('.password-field').forEach(field => {
            field.addEventListener('input', function() {
                validateField(this);
            });
        
            field.addEventListener('blur', function() {
                validateField(this);
            });
        });
        document.querySelectorAll('.password-field').forEach(field => {
        field.addEventListener('input', function() {
            validateField(this);
        });
        
        field.addEventListener('blur', function() {
            validateField(this);
        });
    });

    document.querySelectorAll('.rating-container').forEach(container => {
        initializeRatingField(container);
    });

    document.querySelectorAll('textarea[data-word-limit]').forEach(textarea => {
        const wordLimit = parseInt(textarea.getAttribute('data-word-limit'));
        const showCounter = textarea.getAttribute('data-show-counter') === 'true';
        
        if (showCounter) {
            textarea.addEventListener('input', function() {
                const wordCount = this.value.trim().split(/\s+/).filter(word => word.length > 0).length;
                updateWordCounter(this, wordCount, wordLimit);
            });
        }
    });

    document.querySelectorAll('.rating-item').forEach(function(item) {
        item.addEventListener('click', function() {
            const rating = parseInt(this.getAttribute('data-rating'));
            const fieldId = this.getAttribute('data-field-id');
            const container = this.parentElement;
            const hiddenInput = document.getElementById('rating_input_' + fieldId);
            
            if (hiddenInput) {
                hiddenInput.value = rating;
            }
            
            container.querySelectorAll('.rating-item').forEach(function(ratingItem, index) {
                const itemRating = parseInt(ratingItem.getAttribute('data-rating'));
                if (itemRating <= rating) {
                    if (ratingItem.classList.contains('btn')) {
                        ratingItem.className = 'rating-item btn btn-primary';
                    } else {
                        ratingItem.style.color = getRatingColor(ratingItem);
                    }
                } else {
                    if (ratingItem.classList.contains('btn')) {
                        ratingItem.className = 'rating-item btn btn-outline-primary';
                    } else {
                        ratingItem.style.color = '#ddd';
                    }
                }
            });
        });

        item.addEventListener('mouseenter', function() {
            const rating = parseInt(this.getAttribute('data-rating'));
            const container = this.parentElement;
            
            container.querySelectorAll('.rating-item').forEach(function(ratingItem) {
                const itemRating = parseInt(ratingItem.getAttribute('data-rating'));
                if (itemRating <= rating) {
                    if (!ratingItem.classList.contains('btn')) {
                        ratingItem.style.color = getRatingColor(ratingItem);
                        ratingItem.style.opacity = '0.7';
                    }
                }
            });
        });

        item.addEventListener('mouseleave', function() {
            const container = this.parentElement;
            const hiddenInput = container.querySelector('input[type="hidden"]');
            const currentRating = hiddenInput ? parseInt(hiddenInput.value) : 0;
            
            container.querySelectorAll('.rating-item').forEach(function(ratingItem) {
                const itemRating = parseInt(ratingItem.getAttribute('data-rating'));
                if (!ratingItem.classList.contains('btn')) {
                    if (itemRating <= currentRating) {
                        ratingItem.style.color = getRatingColor(ratingItem);
                        ratingItem.style.opacity = '1';
                    } else {
                        ratingItem.style.color = '#ddd';
                        ratingItem.style.opacity = '1';
                    }
                }
            });
        });
    });


document.querySelectorAll('.month-field').forEach(monthField => {
    initializeMonthField(monthField);
});

function initializeMonthField(field) {
    setMonthDefaultValue(field);
    
    setMonthConstraints(field);
    
    field.addEventListener('input', function() {
        validateMonthField(this);
    });
    
    field.addEventListener('change', function() {
        validateMonthField(this);
    });
}

function setMonthDefaultValue(field) {
    const defaultValue = field.getAttribute('data-default-value');
    
    if (!defaultValue || defaultValue === 'none') return;
    
    let defaultMonth = '';
    const today = new Date();
    const currentYear = today.getFullYear();
    const currentMonth = String(today.getMonth() + 1).padStart(2, '0');
    
    switch(defaultValue) {
        case 'current':
            defaultMonth = `${currentYear}-${currentMonth}`;
            break;
            
        case 'custom':
            const customYear = field.getAttribute('data-custom-year');
            const customMonth = field.getAttribute('data-custom-month');
            if (customYear && customMonth) {
                defaultMonth = `${customYear}-${customMonth}`;
            }
            break;
            
        case 'relative':
            const relativeMonths = parseInt(field.getAttribute('data-relative-months') || '0');
            const targetDate = new Date(currentYear, today.getMonth() + relativeMonths, 1);
            const targetYear = targetDate.getFullYear();
            const targetMonth = String(targetDate.getMonth() + 1).padStart(2, '0');
            defaultMonth = `${targetYear}-${targetMonth}`;
            break;
    }
    
    if (defaultMonth) {
        field.value = defaultMonth;
    }
}

function setMonthConstraints(field) {
    const enableMin = field.getAttribute('data-enable-min') === 'true';
    const enableMax = field.getAttribute('data-enable-max') === 'true';
    const restrictFuture = field.getAttribute('data-restrict-future') === 'true';
    const restrictPast = field.getAttribute('data-restrict-past') === 'true';
    
    let minValue = '';
    let maxValue = '';
    
    if (enableMin) {
        const minYear = field.getAttribute('data-min-year');
        const minMonth = field.getAttribute('data-min-month');
        if (minYear && minMonth) {
            minValue = `${minYear}-${minMonth}`;
        }
    }
    
    if (enableMax) {
        const maxYear = field.getAttribute('data-max-year');
        const maxMonth = field.getAttribute('data-max-month');
        if (maxYear && maxMonth) {
            maxValue = `${maxYear}-${maxMonth}`;
        }
    }
    
    const today = new Date();
    const currentYear = today.getFullYear();
    const currentMonth = String(today.getMonth() + 1).padStart(2, '0');
    const currentMonthValue = `${currentYear}-${currentMonth}`;
    
    if (restrictPast) {
        minValue = minValue ? (minValue > currentMonthValue ? minValue : currentMonthValue) : currentMonthValue;
    }
    
    if (restrictFuture) {
        maxValue = maxValue ? (maxValue < currentMonthValue ? maxValue : currentMonthValue) : currentMonthValue;
    }
    
    if (minValue) field.setAttribute('min', minValue);
    if (maxValue) field.setAttribute('max', maxValue);
}

function validateMonthField(field) {
    const value = field.value;
    if (!value) return true;
    
    let isValid = true;
    let errorMessage = '';
    
    const pleaseselect = _t('Please select');
    const orlater = _t('or later.');
    const pleaseselect2 = _t('Please select');
    const orearlier = _t('or earlier.');
    const futuremonthsnotallowed = _t('Future months are not allowed.');
    const pastmonthsnotallowed = _t('Past months are not allowed.');
    
    const minValue = field.getAttribute('min');
    const maxValue = field.getAttribute('max');
    const restrictFuture = field.getAttribute('data-restrict-future') === 'true';
    const restrictPast = field.getAttribute('data-restrict-past') === 'true';
    
    if (minValue && value < minValue) {
        isValid = false;
        errorMessage = `${pleaseselect} ${formatMonthForDisplay(minValue)} ${orlater}`;
    }
    
    if (maxValue && value > maxValue) {
        isValid = false;
        errorMessage = `${pleaseselect2} ${formatMonthForDisplay(maxValue)} ${orearlier}`;
    }
    
    const today = new Date();
    const currentYear = today.getFullYear();
    const currentMonth = String(today.getMonth() + 1).padStart(2, '0');
    const currentMonthValue = `${currentYear}-${currentMonth}`;
    
    if (restrictFuture && value > currentMonthValue) {
        isValid = false;
        errorMessage = futuremonthsnotallowed;
    }
    
    if (restrictPast && value < currentMonthValue) {
        isValid = false;
        errorMessage = pastmonthsnotallowed;
    }
    
    let errorDiv = field.parentElement.querySelector('.month-error');
    if (!errorDiv) {
        errorDiv = document.createElement('div');
        errorDiv.className = 'month-error invalid-feedback';
        field.parentElement.appendChild(errorDiv);
    }
    
    if (!isValid) {
        field.classList.add('is-invalid');
        field.classList.remove('is-valid');
        errorDiv.textContent = errorMessage;
        errorDiv.style.display = 'block';
    } else {
        field.classList.remove('is-invalid');
        field.classList.add('is-valid');
        errorDiv.style.display = 'none';
    }
    
    return isValid;
}

function formatMonthForDisplay(monthValue) {
    if (!monthValue) return '';
    
    const [year, month] = monthValue.split('-');
    
    const monthNames = [
        _t('January'),
        _t('February'),
        _t('March'),
        _t('April'),
        _t('May'),
        _t('June'),
        _t('July'),
        _t('August'),
        _t('September'),
        _t('October'),
        _t('November'),
        _t('December')
    ];
    
    const monthIndex = parseInt(month) - 1;
    return `${monthNames[monthIndex]} ${year}`;
}

document.querySelectorAll('.time-field').forEach(timeField => {
    setTimeDefaultValue(timeField);
});

function setTimeDefaultValue(field) {
    const defaultValue = field.getAttribute('data-default-value');
    
    if (!defaultValue || defaultValue === 'none') return;
    
    let defaultTime = '';
    
    switch(defaultValue) {
        case 'current':
            const now = new Date();
            const currentHour = String(now.getHours()).padStart(2, '0');
            const currentMinute = String(now.getMinutes()).padStart(2, '0');
            defaultTime = `${currentHour}:${currentMinute}`;
            break;
            
        case 'custom':
            const customHour = field.getAttribute('data-custom-hour') || '9';
            const customMinute = field.getAttribute('data-custom-minute') || '0';
            defaultTime = `${String(customHour).padStart(2, '0')}:${String(customMinute).padStart(2, '0')}`;
            break;
    }
    
    if (defaultTime) {
        field.value = defaultTime;
    }
}

    function getRatingColor(element) {
        const content = element.textContent.trim();
        switch(content) {
            case '★': return '#ffc107'; // Gold for stars
            case '♥': return '#e91e63'; // Pink for hearts  
            case '👍︎': return '#ffc107'; // Green for thumbs
            default: return '#ffc107';
        }
    }

    function validateField(field) {
        let isValid = true;
        let errorMessage = '';
        const fieldType = (field.classList.contains('password-field') ? 'password' : 
                        (field.classList.contains('g-recaptcha') ? 'captcha' : 
                        (field.type || field.tagName.toLowerCase())));        const value = field.value.trim();
        const fieldId = field.id;
        const errorDiv = document.getElementById(fieldId.replace(fieldType + '_', fieldType + '_error_'));

        field.classList.remove('is-invalid', 'is-valid');
        if (errorDiv) {
            errorDiv.textContent = '';
        }

        if (field.hasAttribute('required') && !value) {
            isValid = false;
            errorMessage = _t('This field is required.');
        }

        if (value && isValid) {
            switch(fieldType) {
                case 'text':
                    isValid = validateTextField(field, value);
                    if (!isValid) errorMessage = getTextFieldError(field, value);
                    break;
                    
                case 'number':
                    isValid = validateNumberField(field, value);
                    if (!isValid) errorMessage = getNumberFieldError(field, value);
                    break;
                    
                case 'email':
                    isValid = validateEmailField(field, value);
                    if (!isValid) {
                        const domainRestriction = field.getAttribute('data-domain-restriction') === 'true';
                        const customDomainMsg = field.getAttribute('data-domain-message');
                        if (domainRestriction && !(/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value))) {
                            errorMessage = _t('Please enter a valid email address.');
                        } else if (domainRestriction && customDomainMsg) {
                            errorMessage = customDomainMsg;
                        } else {
                            errorMessage = _t('Please enter a valid email address.');
                        }
                    }
                    break;
                    
                case 'tel':
                    isValid = validatePhoneField(field, value);
                    if (!isValid) errorMessage = getPhoneFieldError(field, value);
                    break;
                case 'date':
                    if (field.classList.contains('year-picker')) {
                        isValid = validateYearField(field, value);
                        if (!isValid) errorMessage = getYearFieldError(field, value);
                    }
                    break;

                case 'select-one':
                    if (field.id.startsWith('year_')) {
                        isValid = validateYearField(field, value);
                        if (!isValid) errorMessage = getYearFieldError(field, value);
                    }
                    if (field.hasAttribute('required') && value === '') {
                        isValid = false;
                        errorMessage = _t('Please make a selection.');
                    }
                    break;

                case 'url':
                    isValid = validateURLField(field, value);
                    if (!isValid) errorMessage = field.getAttribute('data-validation-message') || getURLFieldError(field, value);
                    break;

                case 'textarea':
                    const wordLimit = parseInt(field.getAttribute('data-word-limit') || '0');
                    if (wordLimit > 0) {
                        isValid = validateTextareaField(field, value);
                        if (!isValid) errorMessage = `Please limit your response to ${wordLimit} words.`;
                    }
                    break;
                case 'password':
                    isValid = validatePasswordField(field, value);
                    if (!isValid) errorMessage = getPasswordFieldError(field, value);
                    break;

                case 'file':
                    isValid = validateFileField(field);
                    if (!isValid) errorMessage = getFileFieldError(field);
                    break;
                case 'captcha':
                    
                        isValid = validateCaptchaField(field);
                        if (!isValid) errorMessage = _t('Please complete the CAPTCHA.');
                    
                    break;
            }
        }

    if (!isValid && value !== '') {
        field.classList.add('is-invalid');
        if (errorDiv) {
            errorDiv.textContent = errorMessage;
            errorDiv.style.display = 'block';
        }
        if (fieldType === 'password') {
            const strengthDiv = document.getElementById(field.id.replace('password_', 'strength_'));
            if (strengthDiv) strengthDiv.style.display = 'none';
        }
    } else if (value !== '' && isValid) {
        field.classList.add('is-valid');
        if (fieldType === 'password' && field.getAttribute('data-show-strength') === 'true') {
            updatePasswordStrength(field, value);
        }
    }

        return isValid;
    }

function validatePasswordField(field, value) {
    const minLength = parseInt(field.getAttribute('minlength') || '8');
    const maxLength = parseInt(field.getAttribute('maxlength') || '128');
    const requireUpper = field.getAttribute('data-require-uppercase') === 'true';
    const requireLower = field.getAttribute('data-require-lowercase') === 'true';
    const requireNumber = field.getAttribute('data-require-number') === 'true';
    const requireSpecial = field.getAttribute('data-require-special') === 'true';
    
    if (value.length < minLength || value.length > maxLength) {
        return false;
    }
    
    if (requireUpper && !/[A-Z]/.test(value)) {
        return false;
    }
    
    if (requireLower && !/[a-z]/.test(value)) {
        return false;
    }
    
    if (requireNumber && !/[0-9]/.test(value)) {
        return false;
    }
    
    if (requireSpecial && !/[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\\/~`]/.test(value)) {
        return false;
    }
    
    return true;
}

function getPasswordFieldError(field, value) {
    const customMessage = field.getAttribute('data-validation-message');
    const minLength = parseInt(field.getAttribute('minlength') || '8');
    const maxLength = parseInt(field.getAttribute('maxlength') || '128');
    const requireUpper = field.getAttribute('data-require-uppercase') === 'true';
    const requireLower = field.getAttribute('data-require-lowercase') === 'true';
    const requireNumber = field.getAttribute('data-require-number') === 'true';
    const requireSpecial = field.getAttribute('data-require-special') === 'true';
    
    const passwordmustbeat = _t('Password must be at least');
    const characterslong = _t('characters long');
    const passwordmustnotexceed = _t('Password must not exceed');
    const passwordmustcontain = _t('Password must contain:');
    const oneuppercase = _t('one uppercase letter');
    const onelowercase = _t('one lowercase letter');
    const onenumber = _t('one number');
    const onespecial = _t('one special character');
    
    const requirements = [];

    if (value.length < minLength) {
        return `${passwordmustbeat} ${minLength} ${characterslong}`;
    }
    
    if (value.length > maxLength) {
        return `${passwordmustnotexceed} ${maxLength} ${characterslong}`;
    }
    
    if (requireUpper && !/[A-Z]/.test(value)) {
        requirements.push(oneuppercase);
    }
    
    if (requireLower && !/[a-z]/.test(value)) {
        requirements.push(onelowercase);
    }
    
    if (requireNumber && !/[0-9]/.test(value)) {
        requirements.push(onenumber);
    }
    
    if (requireSpecial && !/[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\\/~`]/.test(value)) {
        requirements.push(onespecial);
    }
    
    if (requirements.length > 0) {
        return `${passwordmustcontain} ${requirements.join(', ')}`;
    }
    
    return customMessage || _t('Invalid password format');
}

function updatePasswordStrength(field, value) {
    const strengthDiv = document.getElementById(field.id.replace('password_', 'strength_'));
    if (!strengthDiv) return;
    
    strengthDiv.style.display = 'block';
    
    let strength = 0;
    let strengthText = '';
    let strengthColor = '';

    const veryweak = _t('Very Weak');
    const weak = _t('Weak');
    const fair = _t('Fair');
    const strong = _t('Strong');
    const verystrong = _t('Very Strong');
    const passwordstrength = _t('Password Strength:');
    
    if (value.length >= 8) strength++;
    if (value.length >= 12) strength++;
    if (/[a-z]/.test(value) && /[A-Z]/.test(value)) strength++;
    if (/[0-9]/.test(value)) strength++;
    if (/[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\\/~`]/.test(value)) strength++;
    
    switch(strength) {
        case 0:
        case 1:
            strengthText = veryweak;
            strengthColor = '#dc3545';
            break;
        case 2:
            strengthText = weak;
            strengthColor = '#fd7e14';
            break;
        case 3:
            strengthText = fair;
            strengthColor = '#ffc107';
            break;
        case 4:
            strengthText = strong;
            strengthColor = '#28a745';
            break;
        case 5:
            strengthText = verystrong;
            strengthColor = '#20c997';
            break;
    }
    
    const percentage = (strength / 5) * 100;
    
    strengthDiv.innerHTML = `
        <div class="progress" style="height: 6px; background-color: #e9ecef;">
            <div class="progress-bar" role="progressbar" 
                 style="width: ${percentage}%; background-color: ${strengthColor}; transition: all 0.3s ease;">
            </div>
        </div>
        <small style="color: ${strengthColor}; font-weight: 500; margin-top: 4px; display: block;">
            ${passwordstrength} ${strengthText}
        </small>
    `;
}
function validateCaptchaField(field) {
    const fieldId = field.id;
    const captchaId = fieldId.replace('captcha_response_', 'captcha_');
    const captchaContainer = document.getElementById(captchaId);
    
    if (!captchaContainer || typeof grecaptcha === 'undefined') {
        console.error('Captcha container or grecaptcha not found');
        return false;
    }
    
    const widgetId = captchaContainer.getAttribute('data-widget-id');
    const response = widgetId !== null ? grecaptcha.getResponse(widgetId) : grecaptcha.getResponse();
    
    if (!response || response.length === 0) {
        return false;
    }
    
    field.value = response;
    return true;
}function validateCaptchaField(field) {
    const fieldId = field.id;
    const captchaId = fieldId.replace('captcha_response_', 'captcha_');
    const captchaContainer = document.getElementById(captchaId);
    
    if (!captchaContainer || typeof grecaptcha === 'undefined') {
        console.error('Captcha container or grecaptcha not found');
        return false;
    }
    
    const widgetId = captchaContainer.getAttribute('data-widget-id');
    const response = widgetId !== null ? grecaptcha.getResponse(widgetId) : grecaptcha.getResponse();
    
    if (!response || response.length === 0) {
        return false;
    }
    
    field.value = response;
    return true;
}
function onCaptchaSuccess(token) {
    const hiddenInput = document.querySelector('.captcha-response');
    if (hiddenInput) {
        hiddenInput.value = token;
        hiddenInput.classList.remove('is-invalid');
        hiddenInput.classList.add('is-valid');
    }
}

function getCaptchaFieldError(field) {
    return _t('Please complete the CAPTCHA.');
}

function validateFileField(field) {
    const files = field.files;
    if (!files || files.length === 0) return !field.hasAttribute('required');
    
    const maxSize = parseInt(field.getAttribute('data-max-size'));
    const allowedExtensions = field.getAttribute('data-allowed-extensions');
    
    for (let file of files) {
        if (maxSize && file.size > maxSize) return false;
        
        if (allowedExtensions) {
            const ext = file.name.split('.').pop().toLowerCase();
            const allowed = allowedExtensions.toLowerCase().split(',');
            if (!allowed.includes(ext)) return false;
        }
    }
    
    if (field.getAttribute('data-show-preview') === 'true') {
        showFilePreview(field, files);
    }
    
    return true;
}

function getFileFieldError(field) {
    const customMessage = field.getAttribute('data-validation-message');
    if (customMessage) return customMessage;
    
    const files = field.files;
    const maxSize = parseInt(field.getAttribute('data-max-size'));
    const allowedExtensions = field.getAttribute('data-allowed-extensions');
    
    const filesizemustnotexceed = _t('File size must not exceed');
    const mb = _t('MB');
    const onlyfilesallowed = _t('Only');
    const filesareallowed = _t('files are allowed');

    for (let file of files) {
        if (maxSize && file.size > maxSize) {
            return `${filesizemustnotexceed} ${maxSize / (1024 * 1024)} ${mb}`;
        }
        
        if (allowedExtensions) {
            const ext = file.name.split('.').pop().toLowerCase();
            const allowed = allowedExtensions.toLowerCase().split(',');
            if (!allowed.includes(ext)) {
                return `${onlyfilesallowed} ${allowedExtensions} ${filesareallowed}`;
            }
        }
    }
    
    return _t('Invalid file');
}

function handleFileUpload(input) {
    const showPreview = input.getAttribute('data-show-preview') === 'true';
    
    if (showPreview && input.files.length > 0) {
        showFilePreview(input, input.files);
    }
    
    validateField(input);
}

function showFilePreview(field, files) {
    const previewDiv = document.getElementById(field.id.replace('file_', 'preview_'));
    if (!previewDiv) return;
    
    previewDiv.innerHTML = '';
    
    const fileArray = Array.from(files);
    
    fileArray.forEach((file, index) => {
        const preview = document.createElement('div');
        preview.className = 'file-preview-item d-flex align-items-center justify-content-between p-2 mb-2 border rounded';
        preview.style.backgroundColor = '#f8f9fa';
        preview.style.display = 'flex';
        preview.style.alignItems = 'center';
        preview.style.justifyContent = 'space-between';
        preview.style.padding = '7px';

        
        const fileInfo = document.createElement('div');
        fileInfo.className = 'd-flex align-items-center';
        fileInfo.style.display = 'flex';
        fileInfo.style.alignItems = 'top';
        fileInfo.style.gap = '10px';

        fileInfo.innerHTML = `
            <i class="fas fa-file me-2" style="color: #6c757d; margin-top:5px;"></i>
            <div>
                <div style="font-weight: 500;">${file.name}</div>
                <small style="color: #6c757d;">${(file.size / 1024).toFixed(2)} KB</small>
            </div>
        `;
        
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'btn btn-sm btn-danger';
        removeBtn.innerHTML = '<i class="fa fa-times"></i>';
        removeBtn.onclick = function() {
            removeFile(field, index);
        };
        
        preview.appendChild(fileInfo);
        preview.appendChild(removeBtn);
        previewDiv.appendChild(preview);
    });
}

function removeFile(input, indexToRemove) {
    const allowMultiple = input.getAttribute('data-multiple') === 'true';
    const dt = new DataTransfer();
    const files = input.files;
    
    for (let i = 0; i < files.length; i++) {
        if (i !== indexToRemove) {
            dt.items.add(files[i]);
        }
    }
    
    input.files = dt.files;
    
    if (allowMultiple && window.fileStorage) {
        window.fileStorage[input.id] = Array.from(input.files);
        input.setAttribute('data-file-count', input.files.length);
    }
    
    if (input.files.length > 0) {
        showFilePreview(input, input.files);
    } else {
        const previewDiv = document.getElementById(input.id.replace('file_', 'preview_'));
        if (previewDiv) {
            previewDiv.innerHTML = '';
        }
        
        if (allowMultiple) {
            input.style.display = 'block';
            const addMoreBtn = document.getElementById('add_more_' + input.id.replace('file_', ''));
            if (addMoreBtn) {
                addMoreBtn.style.display = 'none';
            }
            if (window.fileStorage) {
                delete window.fileStorage[input.id];
            }
            input.removeAttribute('data-file-count');
        }
    }
    
    validateField(input);
}


    function validateTextField(field, value) {
        const minLength = field.getAttribute('data-min-length');
        const maxLength = field.getAttribute('data-max-length');
        const pattern = field.getAttribute('data-pattern');

        if (minLength && value.length < parseInt(minLength)) return false;
        if (maxLength && value.length > parseInt(maxLength)) return false;
        if (pattern && !new RegExp(pattern).test(value)) return false;

        return true;
    }

    function getTextFieldError(field, value) {
        const minLength = field.getAttribute('data-min-length');
        const maxLength = field.getAttribute('data-max-length');
        const pattern = field.getAttribute('data-pattern');
        
        const minimumchars = _t('Minimum');
        const charactersrequired = _t('characters required.');
        const maximumchars = _t('Maximum');
        const charactersallowed = _t('characters allowed.');
        const invalidformat = _t('Please enter a valid format.');

        if (minLength && value.length < parseInt(minLength)) {
            return `${minimumchars} ${minLength} ${charactersrequired}`;
        }
        if (maxLength && value.length > parseInt(maxLength)) {
            return `${maximumchars} ${maxLength} ${charactersallowed}`;
        }
        if (pattern && !new RegExp(pattern).test(value)) {
            return invalidformat;
        }
        return '';
    }

    function validateNumberField(field, value) {
        const min = field.getAttribute('data-min');
        const max = field.getAttribute('data-max');
        const numValue = parseFloat(value);

        if (isNaN(numValue)) return false;
        if (min && numValue < parseFloat(min)) return false;
        if (max && numValue > parseFloat(max)) return false;

        return true;
    }

    function getNumberFieldError(field, value) {
        const min = field.getAttribute('data-min');
        const max = field.getAttribute('data-max');
        const numValue = parseFloat(value);
        
        const invalidnumber = _t('Please enter a valid number.');
        const valuemustbeat = _t('Value must be at least');
        const valuemustnotexceed = _t('Value must not exceed');

        if (isNaN(numValue)) return invalidnumber;
        if (min && numValue < parseFloat(min)) {
            return `${valuemustbeat} ${min}.`;
        }
        if (max && numValue > parseFloat(max)) {
            return `${valuemustnotexceed} ${max}.`;
        }
        return '';
    }

    function validateEmailField(field, value) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(value)) return false;
        
        const domainRestriction = field.getAttribute('data-domain-restriction') === 'true';
        if (domainRestriction) {
            const restrictionType = field.getAttribute('data-restriction-type');
            const allowedDomains = field.getAttribute('data-allowed-domains');
            
            if (allowedDomains) {
                const emailDomain = value.split('@')[1].toLowerCase();
                const domainList = allowedDomains.split('\n')
                    .map(d => d.trim().toLowerCase())
                    .filter(d => d.length > 0);
                
                const isDomainInList = domainList.some(domain => 
                    emailDomain === domain || emailDomain.endsWith('.' + domain)
                );
                
                if (restrictionType === 'include' && !isDomainInList) return false;
                if (restrictionType === 'exclude' && isDomainInList) return false;
            }
        }
        
        return true;
    }

    function validatePhoneField(field, value) {
        const minLength = field.getAttribute('data-min-length');
        const maxLength = field.getAttribute('data-max-length');

        if (minLength && value.length < parseInt(minLength)) return false;
        if (maxLength && value.length > parseInt(maxLength)) return false;

        const phoneRegex = /^[\d\s\-\(\)\+]+$/;
        return phoneRegex.test(value);
    }

    function getPhoneFieldError(field, value) {
        const minLength = field.getAttribute('data-min-length');
        const maxLength = field.getAttribute('data-max-length');
        
        const phonemustbeat = _t('Phone number must be at least');
        const digitsmin = _t('digits.');
        const phonemustnotexceed = _t('Phone number must not exceed');
        const digitsmax = _t('digits.');
        const invalidphone = _t('Please enter a valid phone number.');

        if (minLength && value.length < parseInt(minLength)) {
            return `${phonemustbeat} ${minLength} ${digitsmin}`;
        }
        if (maxLength && value.length > parseInt(maxLength)) {
            return `${phonemustnotexceed} ${maxLength} ${digitsmax}`;
        }
        
        const phoneRegex = /^[\d\s\-\(\)\+]+$/;
        if (!phoneRegex.test(value)) {
            return invalidphone;
        }
        return '';
    }

function validateYearField(field, value) {
    const min = field.getAttribute('data-min');
    const max = field.getAttribute('data-max');
    
    if (field.tagName === 'SELECT') {
        if (value === '' || value === null) return false;
        const numValue = parseInt(value);
        if (isNaN(numValue)) return false;
        if (min && numValue < parseInt(min)) return false;
        if (max && numValue > parseInt(max)) return false;
        return true;
    }
    
    return true;
}


function validateURLField(field, value) {
    try {
        const url = new URL(value);
        const protocol = field.getAttribute('data-protocol');
        const allowExternal = field.getAttribute('data-external') === 'true';
        
        if (protocol === 'https' && url.protocol !== 'https:') return false;
        if (protocol === 'http_https' && !['http:', 'https:'].includes(url.protocol)) return false;
        
        if (!allowExternal && !url.hostname.includes(window.location.hostname)) return false;
        
        return true;
    } catch (e) {
        return false;
    }
}

function getURLFieldError(field, value) {
    const protocol = field.getAttribute('data-protocol');
    const allowExternal = field.getAttribute('data-external') === 'true';
    
    const httpsisnecessary = _t('HTTPS protocol is required.');
    const httprequired = _t('HTTP or HTTPS protocol is required.');
    const externalnotallowed = _t('External URLs are not allowed.');
    const invalidurl = _t('Please enter a valid URL.');
    
    try {
        const url = new URL(value);
        if (protocol === 'https' && url.protocol !== 'https:') {
            return httpsisnecessary;
        }
        if (protocol === 'http_https' && !['http:', 'https:'].includes(url.protocol)) {
            return httprequired;
        }
        if (!allowExternal && !url.hostname.includes(window.location.hostname)) {
            return externalnotallowed;
        }
    } catch (e) {
        return invalidurl;
    }
    return '';
}

function validateTextareaField(field, value) {
    const wordLimit = parseInt(field.getAttribute('data-word-limit') || '0');
    const showCounter = field.getAttribute('data-show-counter') === 'true';
    
    if (wordLimit > 0) {
        const wordCount = value.trim().split(/\s+/).filter(word => word.length > 0).length;
        if (wordCount > wordLimit) {
            const pleaseimit = _t('Please limit your response to');
            const words = _t('words.');
            field.setAttribute('data-error-msg', `${pleaseimit} ${wordLimit} ${words}`);
            return false;
        }
        
        if (showCounter) {
            updateWordCounter(field, wordCount, wordLimit);
        }
    }
    return true;
}

function updateWordCounter(field, currentCount, limit) {
    let counter = field.parentElement.querySelector('.word-counter');
    if (!counter) {
        counter = document.createElement('div');
        counter.className = 'word-counter text-muted mt-1';
        field.parentElement.appendChild(counter);
    }
    
    counter.innerHTML = `${currentCount}/${limit} words`;
    if (currentCount > limit) {
        counter.classList.add('text-danger');
        counter.classList.remove('text-muted');
    } else {
        counter.classList.add('text-muted');
        counter.classList.remove('text-danger');
    }
}

function initializeRatingField(container) {
    const fieldId = container.dataset.fieldId;
    const ratingItems = container.querySelectorAll('.rating-item');
    const hiddenInput = document.getElementById('rating_input_' + fieldId);
    const allowClear = container.getAttribute('data-allow-clear') === 'true';
    const tooltips = container.getAttribute('data-tooltips');
    const labels = container.getAttribute('data-labels');
    
    if (tooltips) {
        const tooltipList = tooltips.split('\n');
        ratingItems.forEach((item, index) => {
            if (tooltipList[index]) {
                item.title = tooltipList[index].trim();
            }
        });
    }
    
    if (labels) {
        const labelList = labels.split('|');
        let labelContainer = container.querySelector('.rating-labels');
        if (!labelContainer && labelList.length > 0) {
            labelContainer = document.createElement('div');
            labelContainer.className = 'rating-labels d-flex justify-content-between mt-1 text-small text-muted';
            container.appendChild(labelContainer);
            
            labelList.forEach(label => {
                const span = document.createElement('span');
                span.textContent = label.trim();
                span.style.marginLeft = '10px';
                labelContainer.appendChild(span);
            });
        }
    }
    
    if (allowClear) {
        let clearBtn = container.querySelector('.rating-clear');
        if (!clearBtn) {
            clearBtn = document.createElement('button');
            clearBtn.type = 'button';
            clearBtn.className = 'rating-clear btn btn-sm btn-outline-secondary ms-2';
            clearBtn.innerHTML = 'Clear';
            clearBtn.style.height = '20px';
            clearBtn.style.marginTop = '10px';
            clearBtn.style.display = 'flex';
            clearBtn.style.alignItems = 'center';
            clearBtn.style.justifyContent = 'center';
            clearBtn.title = 'Clear rating';
            container.appendChild(clearBtn);
            
            clearBtn.addEventListener('click', function() {
                hiddenInput.value = '0';
                ratingItems.forEach(item => resetRatingItem(item));
            });
        }
    }
}

function resetRatingItem(item) {
    if (item.classList.contains('btn')) {
        item.className = 'rating-item btn btn-outline-primary';
    } else {
        item.style.color = '#ddd';
    }
}

function getYearFieldError(field, value) {
    const min = field.getAttribute('data-min');
    const max = field.getAttribute('data-max');
    
    const pleaseselectyear = _t('Please select a year.');
    const pleaseselect = _t('Please select a valid year.');
    const yearmustbeat = _t('Year must be');
    const orlater = _t('or later.');
    const yearmustbe = _t('Year must be');
    const orearlier = _t('or earlier.');

    if (field.tagName === 'SELECT') {
        if (value === '' || value === null) {
            return pleaseselectyear;
        }
        
        const numValue = parseInt(value);
        if (isNaN(numValue)) return pleaseselect;
        if (min && numValue < parseInt(min)) {
            return `${yearmustbeat} ${min} ${orlater}`;
        }
        if (max && numValue > parseInt(max)) {
            return `${yearmustbe} ${max} ${orearlier}`;
        }
    }
    
    return '';
}
document.querySelector('form').addEventListener('submit', function(e) {
    let isFormValid = true;
    const fields = this.querySelectorAll('.validation-field, .captcha-response');
    
    fields.forEach(field => {
        if (!validateField(field)) {
            isFormValid = false;
        }
    });
    
    if (!isFormValid) {
        e.preventDefault();
        const firstError = this.querySelector('.is-invalid');
        if (firstError) {
            firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }
});
    const form = document.querySelector('form');
        if (form) {
            form.addEventListener('submit', function(e) {
                let isFormValid = true;
                
                document.querySelectorAll('.validation-field').forEach(function(field) {
                    if (!validateField(field)) {
                        isFormValid = false;
                    }
                });
                
                if (!isFormValid) {
                    e.preventDefault();
                    const firstError = document.querySelector('.is-invalid');
                    if (firstError) {
                        firstError.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        firstError.focus();
                    }
                }
            });
        }
});