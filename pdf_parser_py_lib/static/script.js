document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const uploadButton = document.getElementById('uploadButton');
    const pdfUploadInput = document.getElementById('pdfUpload');
    const statusMessageDiv = document.getElementById('statusMessage'); // Used for general status and job-level errors
    const jobIdDisplayDiv = document.getElementById('jobIdDisplay');
    const progressDisplayDiv = document.getElementById('progressDisplay');

    const pdfCanvas = document.getElementById('pdfCanvas');
    const pdfViewPlaceholder = document.getElementById('pdfViewPlaceholder');
    const htmlContentView = document.getElementById('htmlContentView');
    const htmlViewPlaceholder = document.getElementById('htmlViewPlaceholder');
    
    const prevPageButton = document.getElementById('prevPage');
    const nextPageButton = document.getElementById('nextPage');
    const pageIndicator = document.getElementById('pageIndicator');
    const showMetadataButton = document.getElementById('showMetadataButton');
    const metadataDisplay = document.getElementById('metadataDisplay'); // The div itself
    const metadataDisplayArea = document.getElementById('metadataDisplayArea'); // Container, if needed for styling/visibility

    // PDF.js state
    let pdfDoc = null;
    let currentPageNum = 1; 
    let pageRendering = false;
    let pageNumPending = null;
    const initialScale = 1.5; 

    // Job state
    let currentJobId = null;
    let currentJobTotalPages = 0;
    let pollingInterval = null;

    if (window.pdfjsLib) {
        pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/pdfjs/build/pdf.worker.min.js';
    } else {
        console.error("PDF.js library not loaded.");
        statusMessageDiv.textContent = "Error: PDF.js library not found. PDF viewing is disabled.";
        statusMessageDiv.style.color = 'red';
    }

    // --- Upload Logic ---
    uploadButton.addEventListener('click', async () => {
        const file = pdfUploadInput.files[0];
        if (!file) {
            statusMessageDiv.textContent = 'Please select a PDF file.'; statusMessageDiv.style.color = 'red'; return;
        }
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            statusMessageDiv.textContent = 'Invalid file type. Only PDF files.'; statusMessageDiv.style.color = 'red'; return;
        }

        if (pollingInterval) clearInterval(pollingInterval);
        resetUIState(); // Resets more UI elements
        statusMessageDiv.textContent = 'Uploading and initiating parsing...';
        statusMessageDiv.style.color = 'blue';
        uploadButton.disabled = true;
        pdfUploadInput.disabled = true;

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/parse_pdf', { method: 'POST', body: formData });
            if (!response.ok) {
                const errData = await response.json().catch(() => ({detail: "Upload request failed."}));
                throw new Error(`Server error: ${response.status}. ${errData.detail}`);
            }
            const result = await response.json();
            currentJobId = result.job_id;
            if (currentJobId) {
                statusMessageDiv.textContent = 'PDF upload successful. Parsing started.';
                statusMessageDiv.style.color = 'green';
                jobIdDisplayDiv.textContent = `Job ID: ${currentJobId}`;
                startPollingJobStatus(currentJobId);
            } else {
                throw new Error('Job ID not received.');
            }
        } catch (error) {
            console.error('Upload error:', error);
            displayJobError(`Upload failed: ${error.message}`); // Use displayJobError for consistency
            resetUIForNewUpload();
        }
    });

    function resetUIState() {
        jobIdDisplayDiv.textContent = '';
        progressDisplayDiv.textContent = '';
        statusMessageDiv.textContent = ''; // Clear previous status/errors
        statusMessageDiv.style.color = 'black'; // Reset color
        pdfViewPlaceholder.style.display = 'flex'; 
        pdfCanvas.style.display = 'none'; 
        htmlViewPlaceholder.style.display = 'flex'; 
        htmlContentView.style.display = 'none'; 
        htmlContentView.innerHTML = ''; 
        pageIndicator.textContent = 'Page N/A of N/A';
        prevPageButton.disabled = true;
        nextPageButton.disabled = true;
        showMetadataButton.disabled = true;
        metadataDisplay.style.display = 'none'; // Hide metadata display
        metadataDisplay.textContent = ''; // Clear old metadata
        pdfDoc = null;
        currentPageNum = 1;
        currentJobTotalPages = 0;
        // currentJobId is reset when a new upload starts or on critical error.
    }
    
    function resetUIForNewUpload() {
        uploadButton.disabled = false;
        pdfUploadInput.disabled = false;
    }

    function startPollingJobStatus(jobId) {
        if (pollingInterval) clearInterval(pollingInterval);
        pollingInterval = setInterval(async () => {
            try {
                const response = await fetch(`/status/${jobId}`);
                if (!response.ok) {
                    if (response.status === 404) {
                        displayJobError(`Error: Job ID ${jobId} not found. Stopping polling.`);
                    } else {
                        displayJobError(`Error fetching job status: ${response.statusText}. Stopping polling.`);
                    }
                    clearInterval(pollingInterval); resetUIForNewUpload(); return;
                }
                const statusData = await response.json();
                currentJobTotalPages = statusData.num_pages || 0;
                progressDisplayDiv.textContent = `Status: ${statusData.status} (${statusData.num_pages} pages detected)`;

                if (statusData.status === 'completed') {
                    clearInterval(pollingInterval);
                    statusMessageDiv.textContent = 'Processing complete!';
                    statusMessageDiv.style.color = 'green';
                    resetUIForNewUpload();
                    if (currentJobTotalPages > 0) {
                        await loadPdfAndFirstPage(jobId, currentJobTotalPages);
                        showMetadataButton.disabled = false; // Enable metadata button
                    } else {
                        pageIndicator.textContent = 'PDF has 0 pages or page count not determined.';
                        showMetadataButton.disabled = true;
                    }
                } else if (statusData.status === 'error') {
                    clearInterval(pollingInterval);
                    await displayJobError(jobId); // Fetch and display detailed error
                    resetUIForNewUpload();
                    showMetadataButton.disabled = true;
                }
            } catch (error) {
                console.error('Polling error:', error);
                displayJobError(`Polling error: ${error.message}. Stopping polling.`);
                clearInterval(pollingInterval); resetUIForNewUpload();
            }
        }, 3000);
    }

    async function displayJobError(jobIdOrMessage) {
        let errorMessage = jobIdOrMessage;
        if (currentJobId && jobIdOrMessage === currentJobId) { // If it's a job ID, fetch detailed error
            try {
                const errorResponse = await fetch(`/error/${currentJobId}`);
                if (errorResponse.ok) {
                    const errorData = await errorResponse.json();
                    errorMessage = errorData.error_message || 'Unknown processing error for this job.';
                } else {
                    errorMessage = `Could not retrieve error details for job ${currentJobId}. Server status: ${errorResponse.status}.`;
                }
            } catch (fetchErr) {
                errorMessage = `Failed to fetch error details for job ${currentJobId}: ${fetchErr.message}`;
            }
        }
        // Display the final error message
        statusMessageDiv.textContent = `Job Error: ${errorMessage}`;
        statusMessageDiv.style.color = 'red';
        jobIdDisplayDiv.textContent = currentJobId ? `Job ID: ${currentJobId}` : '';
        progressDisplayDiv.textContent = 'Status: Failed';
    }


    async function loadPdfAndFirstPage(jobId, totalPages) {
        const pdfUrl = `/pdf_jobs/${jobId}/document.pdf`;
        try {
            if (!window.pdfjsLib) {
                throw new Error("PDF.js library failed to load.");
            }
            const loadingTask = pdfjsLib.getDocument(pdfUrl);
            pdfDoc = await loadingTask.promise;
            currentJobTotalPages = pdfDoc.numPages; 
            
            pdfViewPlaceholder.style.display = 'none';
            pdfCanvas.style.display = 'block';
            
            currentPageNum = 1; 
            await renderPdfPage(currentPageNum); // Make renderPdfPage async for error handling
            await fetchAndDisplayHtml(jobId, currentPageNum - 1); 
            updatePageNavigationControls();
            metadataDisplay.style.display = 'none'; // Hide metadata from previous job if any

        } catch (error) {
            console.error('Error loading PDF:', error);
            pdfViewPlaceholder.textContent = `Error loading PDF: ${error.message}`;
            pdfViewPlaceholder.style.display = 'flex';
            pdfCanvas.style.display = 'none';
            displayJobError(`Failed to load PDF for viewing: ${error.message}`);
        }
    }

    async function renderPdfPage(num) {
        if (!pdfDoc) return;
        pageRendering = true;
        
        try {
            const page = await pdfDoc.getPage(num);
            const viewport = page.getViewport({ scale: initialScale });
            const canvasContext = pdfCanvas.getContext('2d');
            pdfCanvas.height = viewport.height;
            pdfCanvas.width = viewport.width;

            const renderContext = { canvasContext, viewport };
            await page.render(renderContext).promise;
        } catch (renderErr) {
            console.error("Error rendering page:", renderErr);
            pdfViewPlaceholder.textContent = `Error rendering page ${num}: ${renderErr.message}`;
            pdfViewPlaceholder.style.display = 'flex';
            pdfCanvas.style.display = 'none';
            // Display this error more prominently if needed
        } finally {
            pageRendering = false;
            if (pageNumPending !== null) {
                const pending = pageNumPending;
                pageNumPending = null;
                await renderPdfPage(pending); // Render the queued page
            }
        }

        pageIndicator.textContent = `Page ${num} of ${currentJobTotalPages}`;
        currentPageNum = num; 
        updatePageNavigationControls();
    }

    function queueRenderPage(num) { // This can now call the async renderPdfPage
        if (pageRendering) {
            pageNumPending = num;
        } else {
            renderPdfPage(num); // Directly call async version
        }
    }

    async function fetchAndDisplayHtml(jobId, pageNumApi) { 
        htmlViewPlaceholder.style.display = 'flex';
        htmlViewPlaceholder.textContent = 'Loading HTML content...';
        htmlContentView.style.display = 'none';
        htmlContentView.innerHTML = ''; 
        try {
            const response = await fetch(`/page/${jobId}/${pageNumApi}/html`);
            if (!response.ok) {
                const errorText = await response.text();
                let detail = errorText;
                try { detail = JSON.parse(errorText).detail || errorText; } catch(e){}
                throw new Error(`Failed to fetch HTML: ${response.status}. ${detail}`);
            }
            const htmlText = await response.text();
            htmlContentView.innerHTML = htmlText; // This HTML should include page-level errors from generator
            htmlViewPlaceholder.style.display = 'none';
            htmlContentView.style.display = 'block';
        } catch (error) {
            console.error('Error fetching HTML content:', error);
            htmlContentView.innerHTML = `<p style="color:red;">Could not load HTML content: ${error.message}</p>`;
            htmlViewPlaceholder.style.display = 'none'; // Still hide placeholder
            htmlContentView.style.display = 'block'; // Show the error in the content view
        }
    }
    
    async function fetchAndDisplayRawData(jobId, pageNumApi) {
        if (!jobId) {
            metadataDisplay.textContent = 'No active job selected.';
            metadataDisplay.style.display = 'block';
            return;
        }
        metadataDisplay.textContent = 'Loading raw data...';
        metadataDisplay.style.display = 'block';
        try {
            const response = await fetch(`/page/${jobId}/${pageNumApi}/raw_data`);
            if (!response.ok) {
                const errorText = await response.text();
                let detail = errorText;
                try { detail = JSON.parse(errorText).detail || errorText; } catch(e){}
                throw new Error(`Failed to fetch raw data: ${response.status}. ${detail}`);
            }
            const rawData = await response.json();
            metadataDisplay.textContent = JSON.stringify(rawData, null, 2);
        } catch (error) {
            console.error('Error fetching raw data:', error);
            metadataDisplay.textContent = `Could not load raw data: ${error.message}`;
            metadataDisplay.style.color = 'red'; // Keep color red for error message
        }
    }

    function updatePageNavigationControls() {
        if (currentJobTotalPages > 0 && currentJobId) {
            pageIndicator.textContent = `Page ${currentPageNum} of ${currentJobTotalPages}`;
            prevPageButton.disabled = currentPageNum <= 1;
            nextPageButton.disabled = currentPageNum >= currentJobTotalPages;
            showMetadataButton.disabled = false; // Enable if job is loaded
        } else {
            pageIndicator.textContent = 'Page N/A of N/A';
            prevPageButton.disabled = true;
            nextPageButton.disabled = true;
            showMetadataButton.disabled = true; // Disable if no job/pages
        }
    }

    prevPageButton.addEventListener('click', () => {
        if (currentPageNum <= 1 || !pdfDoc || !currentJobId) return;
        currentPageNum--;
        queueRenderPage(currentPageNum);
        fetchAndDisplayHtml(currentJobId, currentPageNum - 1);
        metadataDisplay.style.display = 'none'; // Hide metadata on page change
        metadataDisplay.textContent = '';
    });

    nextPageButton.addEventListener('click', () => {
        if (currentPageNum >= currentJobTotalPages || !pdfDoc || !currentJobId) return;
        currentPageNum++;
        queueRenderPage(currentPageNum);
        fetchAndDisplayHtml(currentJobId, currentPageNum - 1);
        metadataDisplay.style.display = 'none'; // Hide metadata on page change
        metadataDisplay.textContent = '';
    });

    showMetadataButton.addEventListener('click', () => {
        if (!currentJobId || currentJobTotalPages === 0) return;
        // Toggle display or always fetch and show for current page
        if (metadataDisplay.style.display === 'none') {
            fetchAndDisplayRawData(currentJobId, currentPageNum - 1); // API is 0-indexed
        } else {
            metadataDisplay.style.display = 'none';
            metadataDisplay.textContent = ''; // Clear it
        }
    });

    // Initial UI state
    resetUIState(); 
    resetUIForNewUpload();
});
