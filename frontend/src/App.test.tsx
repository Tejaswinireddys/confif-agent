import { render, screen } from '@testing-library/react';
import App from './App';

test('renders the contract picker as the first step', () => {
  render(<App />);
  expect(screen.getByText(/choose a schema contract/i)).toBeInTheDocument();
});
