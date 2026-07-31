import { useState } from 'react';
import {
  Box,
  Typography,
  Paper,
  TextField,
  Button,
  Alert,
  Snackbar,
  CircularProgress,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material';
import { HelpOutline as HelpIcon, Send as SendIcon, ExpandMore as ExpandMoreIcon } from '@mui/icons-material';
import { useMutation } from '@tanstack/react-query';
import { api } from '../services/api';
import { useAuth } from '../contexts/AuthContext';

export default function Help() {
  const { user } = useAuth();
  const [subject, setSubject] = useState('');
  const [message, setMessage] = useState('');
  const [snackbar, setSnackbar] = useState({
    open: false,
    message: '',
    severity: 'info' as 'success' | 'error' | 'info',
  });

  const sendHelpMutation = useMutation({
    mutationFn: async () => {
      const response = await api.post('/help/contact', {
        subject,
        message,
      });
      return response.data;
    },
    onSuccess: () => {
      setSnackbar({
        open: true,
        message: 'Your message has been sent successfully! We\'ll get back to you soon.',
        severity: 'success',
      });
      setSubject('');
      setMessage('');
    },
    onError: (error: any) => {
      setSnackbar({
        open: true,
        message: error.response?.data?.detail || 'Failed to send message. Please try again.',
        severity: 'error',
      });
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!subject.trim() || !message.trim()) {
      setSnackbar({
        open: true,
        message: 'Please fill in both subject and message fields.',
        severity: 'error',
      });
      return;
    }
    sendHelpMutation.mutate();
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 4 }}>
        <HelpIcon sx={{ fontSize: 40, mr: 2, color: 'primary.main' }} />
        <Box>
          <Typography variant="h2" component="h1">
            Help & Support
          </Typography>
          <Typography variant="body1" color="text.secondary" sx={{ mt: 1 }}>
            Have a question or need assistance? Send us a message and we'll get back to you shortly.
          </Typography>
        </Box>
      </Box>

      <Paper sx={{ p: 4, maxWidth: 800 }}>
        <form onSubmit={handleSubmit}>
          <Box sx={{ mb: 3 }}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Signed in as: <strong>{user?.email}</strong>
            </Typography>
          </Box>

          <TextField
            fullWidth
            label="Subject"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="Brief description of your question or issue"
            sx={{ mb: 3 }}
            required
          />

          <TextField
            fullWidth
            label="Message"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Please provide details about your question or issue..."
            multiline
            rows={8}
            sx={{ mb: 3 }}
            required
          />

          <Button
            type="submit"
            variant="contained"
            size="large"
            startIcon={sendHelpMutation.isPending ? <CircularProgress size={20} color="inherit" /> : <SendIcon />}
            disabled={sendHelpMutation.isPending}
            sx={{
              backgroundColor: '#80A1D4',
              '&:hover': {
                backgroundColor: '#6B8BC0',
              },
            }}
          >
            {sendHelpMutation.isPending ? 'Sending...' : 'Send Message'}
          </Button>
        </form>

      </Paper>

      {/* FAQ Section */}
      <Paper sx={{ p: 4, mt: 4, maxWidth: 800 }}>
        <Typography variant="h5" gutterBottom sx={{ mb: 3 }}>
          Frequently Asked Questions
        </Typography>

        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography fontWeight={500}>How do I set up my account for the first time?</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Setting up TALES is a 4-step process:
            </Typography>
            <Typography variant="body2" color="text.secondary" component="div" sx={{ pl: 2 }}>
              <strong>1. Create Your Brand:</strong> Go to <strong>Customize &gt; Brand Info</strong> and enter your brand name,
              description, and key information. This helps TALES understand what to track.<br /><br />

              <strong>2. Configure Queries, Descriptors & Competitors:</strong> Navigate to <strong>Customize</strong> and set up
              your queries (questions AI platforms will answer), descriptors (key attributes you want to track), and competitors.
              You can enter these manually or use our AI generation feature to automatically create comprehensive sets based on your
              brand information.<br /><br />

              <strong>3. Run Your First Collection:</strong> Go to <strong>Collect & Analyze</strong> and manually run a collection
              followed by analysis to gather your first data set and verify everything is working correctly.<br /><br />

              <strong>4. Set Up Monthly Automation:</strong> Once you've tested manual collection, go to the
              <strong>Automated Schedule</strong> tab in <strong>Collect & Analyze</strong> to set up monthly automated runs.
              Choose your collection day (1st, 15th, or last day of month) and enable email notifications.
            </Typography>
          </AccordionDetails>
        </Accordion>

        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography fontWeight={500}>How do I set up automated monthly data collection?</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Typography variant="body2" color="text.secondary">
              Go to <strong>Collect & Analyze</strong> in the main menu, then click the <strong>Automated Schedule</strong> tab.
              Choose your preferred collection day (1st, 15th, or last day of month), enable the schedule, configure email
              notifications, and click <strong>Save Schedule</strong>. TALES will automatically collect and analyze data on your
              chosen day each month.
            </Typography>
          </AccordionDetails>
        </Accordion>

        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography fontWeight={500}>What AI platforms does TALES collect data from?</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Typography variant="body2" color="text.secondary">
              TALES currently collects responses from major AI platforms including ChatGPT, Claude, Perplexity, and Gemini.
              When you run a collection, TALES queries each platform with your configured queries and gathers responses about
              your brand and competitors.
            </Typography>
          </AccordionDetails>
        </Accordion>

        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography fontWeight={500}>How do I add or edit my brand competitors?</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Typography variant="body2" color="text.secondary">
              Navigate to <strong>Customize</strong> in the main menu, then select <strong>Competitors</strong>. Here you can
              add new competitors by clicking <strong>Add Competitor</strong>, or edit/delete existing ones. Make sure to track
              your key competitors to get comprehensive market positioning insights.
            </Typography>
          </AccordionDetails>
        </Accordion>

        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography fontWeight={500}>What are Descriptors and how should I use them?</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Typography variant="body2" color="text.secondary">
              Descriptors are key attributes or qualities that you want to be associated with your brand (e.g., "innovative,"
              "user-friendly," "affordable"). Add them under <strong>Customize &gt; Descriptors</strong>. TALES analyzes how
              often AI platforms associate these descriptors with your brand versus competitors, helping you understand your
              brand positioning.
            </Typography>
          </AccordionDetails>
        </Accordion>

        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography fontWeight={500}>What's the difference between Collection and Analysis?</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Typography variant="body2" color="text.secondary">
              <strong>Collection</strong> gathers raw responses from AI platforms based on your queries. <strong>Analysis</strong>
              processes those responses using AI to determine brand mentions, sentiment, positioning, and other insights. You
              typically run Collection first, then Analysis. Automated schedules run both automatically in sequence.
            </Typography>
          </AccordionDetails>
        </Accordion>

        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography fontWeight={500}>How do I download or export my reports?</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Typography variant="body2" color="text.secondary">
              After running an analysis, reports are available in the <strong>Reports</strong> page.
              You can view reports in your browser or download them in Word (.docx) or HTML format. Each report includes
              comprehensive insights and charts based on your latest data. You can also export the underlying
              response data as a spreadsheet to analyze yourself or hand to an AI assistant.
            </Typography>
          </AccordionDetails>
        </Accordion>

        <Accordion>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography fontWeight={500}>Can I manage multiple brands with one account?</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Typography variant="body2" color="text.secondary">
              Yes! Use the brand switcher in the top right corner to switch between brands. Each brand has its own queries,
              competitors, descriptors, data collection, and reports. This allows you to track multiple products, services, or
              brands from a single TALES account.
            </Typography>
          </AccordionDetails>
        </Accordion>

        <Box sx={{ mt: 4, pt: 3, borderTop: '1px solid #e0e0e0' }}>
          <Typography variant="body2" color="text.secondary">
            For more detailed information about how TALES works, visit the{' '}
            <a href="/how-tales-works" style={{ color: '#80A1D4', textDecoration: 'none', fontWeight: 500 }}>
              How TALES Works
            </a>{' '}
            page. Still have questions? Use the contact form above to reach out to our support team.
          </Typography>
        </Box>
      </Paper>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={6000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      >
        <Alert severity={snackbar.severity}>{snackbar.message}</Alert>
      </Snackbar>
    </Box>
  );
}
